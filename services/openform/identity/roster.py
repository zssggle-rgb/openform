from typing import Any
from uuid import UUID, uuid4

from openform_contracts.permissions import AccessFacts, permits
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from openform.errors import ApiError
from openform.identity.context import StaffIdentity, require_admin, workspace_transaction
from openform.identity.roster_schemas import (
    AssignmentInput,
    ClassChangeInput,
    ClassInput,
    StudentChangeInput,
    StudentInput,
)


def _page(rows: list[dict[str, Any]], key: str = "id") -> dict[str, Any]:
    return {"items": rows[:50], "next_cursor": str(rows[49][key]) if len(rows) > 50 else None}


def _event(connection: Connection, workspace_id: UUID, actor_id: UUID, action: str, target_id: UUID) -> None:
    connection.execute(text("INSERT INTO identity_events (workspace_id, id, actor_id, action, target_id) "
                            "VALUES (:workspace, :id, :actor, :action, :target)"),
                       {"workspace": workspace_id, "id": uuid4(), "actor": actor_id, "action": action, "target": target_id})


def require_class(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any],
                  class_id: UUID, *, manage: bool = False) -> dict[str, Any]:
    classroom = connection.execute(text("SELECT * FROM classes WHERE workspace_id=:space AND id=:id FOR SHARE"),
                                   {"space": workspace["id"], "id": class_id}).mappings().one_or_none()
    if classroom is None:
        raise ApiError(404, "NOT_FOUND", "班级不存在。")
    assigned = connection.execute(text("SELECT active FROM assignments WHERE workspace_id=:space "
                                       "AND class_id=:class AND account_id=:actor FOR SHARE"),
                                  {"space": workspace["id"], "class": class_id, "actor": identity.account_id}).scalar_one_or_none()
    facts = AccessFacts(actor_id=str(identity.account_id), actor_kind="staff", workspace_id=str(workspace["id"]),
                        target_workspace_id=str(classroom["workspace_id"]), workspace_active=True, membership_active=True,
                        roles=frozenset(role for role, valid in (("teacher", workspace["is_teacher"]), ("admin", workspace["is_admin"])) if valid),
                        personal_owner=workspace["kind"] == "personal" and workspace["owner_id"] == identity.account_id,
                        assigned_class=assigned is True)
    if (not permits("class.manage" if manage else "class.read", facts)
            or not classroom["active"] and not workspace["is_admin"]):
        raise ApiError(403, "FORBIDDEN", "你没有该班级的名单或管理权限。")
    return dict(classroom)


def require_student(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any],
                    student_id: UUID) -> dict[str, Any]:
    student = connection.execute(text("SELECT * FROM students WHERE workspace_id=:space AND id=:id FOR SHARE"),
                                 {"space": workspace["id"], "id": student_id}).mappings().one_or_none()
    if student is None:
        raise ApiError(404, "NOT_FOUND", "学生条目不存在。")
    if not workspace["is_admin"]:
        if student["class_id"] is None:
            raise ApiError(403, "FORBIDDEN", "该学生尚未属于你有权使用的班级。")
        require_class(connection, identity, workspace, student["class_id"])
    return dict(student)


def list_classes(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                 cursor: UUID | None = None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        rows = connection.execute(text("""
            SELECT c.id, c.name, c.active, c.revision,
              (SELECT count(*) FROM students s WHERE s.workspace_id=c.workspace_id AND s.class_id=c.id AND s.active) AS student_count
            FROM classes c WHERE c.workspace_id=:space AND (CAST(:cursor AS uuid) IS NULL OR c.id>CAST(:cursor AS uuid))
              AND (:admin OR (:teacher AND c.active AND EXISTS (SELECT 1 FROM assignments a
                WHERE a.workspace_id=c.workspace_id AND a.class_id=c.id AND a.account_id=:actor AND a.active)))
            ORDER BY c.id LIMIT 51
        """), {"space": workspace_id, "cursor": cursor, "admin": workspace["is_admin"],
               "teacher": workspace["is_teacher"], "actor": identity.account_id}).mappings().all()
        return _page([dict(row) for row in rows])


def create_class(engine: Engine, identity: StaffIdentity, workspace_id: UUID, data: ClassInput) -> UUID:
    class_id = uuid4()
    try:
        with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
            require_admin(workspace)
            connection.execute(text("INSERT INTO classes (workspace_id, id, name) VALUES (:space, :id, :name)"),
                               {"space": workspace_id, "id": class_id, "name": data.name})
            _event(connection, workspace_id, identity.account_id, "class.created", class_id)
    except IntegrityError:
        raise ApiError(409, "INVALID_INPUT", "当前空间已有同名班级，请检查名称。") from None
    return class_id


def change_class(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                 class_id: UUID, data: ClassChangeInput) -> None:
    try:
        with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
            classroom = require_class(connection, identity, workspace, class_id, manage=True)
            if classroom["revision"] != data.expected_revision:
                raise ApiError(409, "REVISION_CONFLICT", "班级已变化，请刷新后重试。")
            connection.execute(text("UPDATE classes SET name=:name, active=:active, revision=revision+1 "
                                    "WHERE workspace_id=:space AND id=:id"),
                               {"space": workspace_id, "id": class_id, "name": data.name, "active": data.active})
            _event(connection, workspace_id, identity.account_id, "class.changed", class_id)
    except IntegrityError:
        raise ApiError(409, "INVALID_INPUT", "当前空间已有同名班级，请检查名称。") from None


def list_assignments(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                     class_id: UUID, cursor: UUID | None = None, account_id: UUID | None = None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_class(connection, identity, workspace, class_id)
        rows = connection.execute(text("""
            SELECT t.account_id, a.display_name, t.subject, t.active, t.revision,
              m.active AND a.active AND m.is_teacher AS member_eligible
            FROM assignments t JOIN accounts a ON a.id=t.account_id
            JOIN memberships m ON m.workspace_id=t.workspace_id AND m.account_id=t.account_id
            WHERE t.workspace_id=:space AND t.class_id=:class
              AND (CAST(:account AS uuid) IS NULL OR t.account_id=CAST(:account AS uuid))
              AND (CAST(:cursor AS uuid) IS NULL OR t.account_id>CAST(:cursor AS uuid)) ORDER BY t.account_id LIMIT 51
        """), {"space": workspace_id, "class": class_id, "cursor": cursor, "account": account_id}).mappings().all()
        return _page([dict(row) for row in rows], "account_id")


def change_assignment(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                      class_id: UUID, account_id: UUID, data: AssignmentInput) -> None:
    with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
        require_class(connection, identity, workspace, class_id, manage=True)
        member = connection.execute(text("SELECT m.active AND a.active AND m.is_teacher AS eligible FROM memberships m "
                                         "JOIN accounts a ON a.id=m.account_id WHERE m.workspace_id=:space "
                                         "AND m.account_id=:id FOR SHARE OF m, a"),
                                    {"space": workspace_id, "id": account_id}).mappings().one_or_none()
        if member is None or data.active and not member["eligible"]:
            raise ApiError(403, "FORBIDDEN", "任课必须指向本空间有效的教师成员。")
        previous = connection.execute(text("SELECT revision FROM assignments WHERE workspace_id=:space "
                                           "AND class_id=:class AND account_id=:id FOR UPDATE"),
                                      {"space": workspace_id, "class": class_id, "id": account_id}).scalar_one_or_none()
        if (previous or 0) != data.expected_revision:
            raise ApiError(409, "REVISION_CONFLICT", "任课关系已变化，请刷新后重试。")
        connection.execute(text("""
            INSERT INTO assignments (workspace_id, class_id, account_id, subject, active)
            VALUES (:space, :class, :id, :subject, :active)
            ON CONFLICT (workspace_id, class_id, account_id) DO UPDATE
              SET subject=EXCLUDED.subject, active=EXCLUDED.active, revision=assignments.revision+1
        """), {"space": workspace_id, "class": class_id, "id": account_id, "subject": data.subject, "active": data.active})
        _event(connection, workspace_id, identity.account_id, "assignment.changed", class_id)


def list_students(engine: Engine, identity: StaffIdentity, workspace_id: UUID, *, class_id: UUID | None = None,
                  cursor: UUID | None = None, query: str = "") -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        if class_id is not None:
            require_class(connection, identity, workspace, class_id)
        query = query.strip()
        if len(query) > 80:
            raise ApiError(422, "INVALID_INPUT", "学生搜索不超过 80 个字符。")
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = connection.execute(text("""
            SELECT s.id, s.reference, s.display_name, s.class_id, c.name AS class_name, s.active, s.revision,
              s.auth_epoch, s.code_digest IS NOT NULL AND s.code_expires_at>now() AS has_code
            FROM students s LEFT JOIN classes c ON c.workspace_id=s.workspace_id AND c.id=s.class_id
            WHERE s.workspace_id=:space AND (CAST(:cursor AS uuid) IS NULL OR s.id>CAST(:cursor AS uuid))
              AND (CAST(:class AS uuid) IS NULL OR s.class_id=CAST(:class AS uuid))
              AND (s.display_name ILIKE :pattern OR s.reference ILIKE :pattern)
              AND (:admin OR (:teacher AND c.active AND EXISTS (SELECT 1 FROM assignments a
                WHERE a.workspace_id=s.workspace_id AND a.class_id=s.class_id AND a.account_id=:actor AND a.active)))
            ORDER BY s.id LIMIT 51
        """), {"space": workspace_id, "class": class_id, "cursor": cursor, "pattern": pattern,
               "admin": workspace["is_admin"], "teacher": workspace["is_teacher"], "actor": identity.account_id}).mappings().all()
        return _page([dict(row) for row in rows])


def create_student(engine: Engine, identity: StaffIdentity, workspace_id: UUID, data: StudentInput) -> UUID:
    student_id = uuid4()
    try:
        with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
            require_admin(workspace)
            if data.class_id is not None:
                classroom = require_class(connection, identity, workspace, data.class_id, manage=True)
                if not classroom["active"]:
                    raise ApiError(409, "STATE_CONFLICT", "不能将学生分入已停用班级。")
            connection.execute(text("INSERT INTO students (workspace_id, id, reference, display_name, class_id) "
                                    "VALUES (:space, :id, :reference, :name, :class)"),
                               {"space": workspace_id, "id": student_id, "reference": data.reference,
                                "name": data.display_name, "class": data.class_id})
            _event(connection, workspace_id, identity.account_id, "student.created", student_id)
    except IntegrityError:
        raise ApiError(409, "INVALID_INPUT", "当前空间已有相同学生编号，不按姓名自动合并。") from None
    return student_id


def change_student(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                   student_id: UUID, data: StudentChangeInput) -> None:
    try:
        with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
            require_admin(workspace)
            student = require_student(connection, identity, workspace, student_id)
            if student["revision"] != data.expected_revision:
                raise ApiError(409, "REVISION_CONFLICT", "学生条目已变化，请刷新后重试。")
            if data.class_id is not None:
                classroom = require_class(connection, identity, workspace, data.class_id, manage=True)
                if not classroom["active"] and data.class_id != student["class_id"]:
                    raise ApiError(409, "STATE_CONFLICT", "不能将学生分入已停用班级。")
            connection.execute(text("""
                UPDATE students SET reference=:reference, display_name=:name, class_id=:class,
                  auth_epoch=auth_epoch+CASE WHEN active<>:active THEN 1 ELSE 0 END,
                  code_digest=CASE WHEN active<>:active THEN NULL ELSE code_digest END,
                  code_expires_at=CASE WHEN active<>:active THEN NULL ELSE code_expires_at END,
                  active=:active, revision=revision+1 WHERE workspace_id=:space AND id=:id
            """), {"space": workspace_id, "id": student_id, "reference": data.reference, "name": data.display_name,
                   "class": data.class_id, "active": data.active})
            _event(connection, workspace_id, identity.account_id, "student.changed", student_id)
    except IntegrityError:
        raise ApiError(409, "INVALID_INPUT", "当前空间已有相同学生编号，请核对名单。") from None
