import hashlib
import json
import secrets
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from openform.classrooms.schemas import ClassroomInput, StateInput
from openform.errors import ApiError
from openform.identity.authorization import register_object, require_object
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.roster import _event, _page


def require_classroom(connection: Connection, workspace_id: UUID, classroom_id: UUID, *, write: bool = False) -> dict[str, Any]:
    lock = "UPDATE" if write else "SHARE"
    row = connection.execute(text(f"SELECT * FROM classrooms WHERE workspace_id=:space AND id=:id FOR {lock}"),
                             {"space": workspace_id, "id": classroom_id}).mappings().one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "课堂不存在。")
    if row["records_deleted_at"] is not None:
        raise ApiError(410, "RECORDS_DELETED", "此课堂资料已删除或保留到期，原进度、提交和报告不可读取。")
    return dict(row)


def teaching_class(connection: Connection, identity: StaffIdentity, workspace_id: UUID, class_id: UUID) -> None:
    assigned = connection.execute(text("SELECT active FROM assignments WHERE workspace_id=:space "
                                       "AND class_id=:class AND account_id=:actor FOR SHARE"),
                                  {"space": workspace_id, "class": class_id, "actor": identity.account_id}).scalar_one_or_none()
    active = connection.execute(text("SELECT active FROM classes WHERE workspace_id=:space AND id=:class FOR SHARE"),
                                {"space": workspace_id, "class": class_id}).scalar_one_or_none()
    if assigned is not True or active is not True:
        raise ApiError(403, "FORBIDDEN", "需要该有效班级的当前任课权限。")


def _roster(connection: Connection, workspace_id: UUID, class_id: UUID, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = connection.execute(text("SELECT id, display_name, reference FROM students WHERE workspace_id=:space "
                                   "AND class_id=:class AND active ORDER BY id FOR SHARE"),
                              {"space": workspace_id, "class": class_id}).mappings().all()
    if not groups:
        return [{**dict(row), "group_name": None, "members": []} for row in rows]
    people = {str(row["id"]): dict(row) for row in rows}
    used: set[str] = set()
    result = []
    for group in groups:
        members = group["members"]
        if (len(set(members)) != len(members) or group["recorder_id"] not in members
                or any(member not in people or member in used for member in members) or not group["name"].strip()):
            raise ApiError(422, "INVALID_INPUT", "小组成员必须是本班有效学生且不重复，记录员必须属于本组。")
        used.update(members)
        result.append({**people[group["recorder_id"]], "group_name": group["name"], "members": [UUID(value) for value in members]})
    return result


def create_classroom(engine: Engine, identity: StaffIdentity, workspace_id: UUID, data: ClassroomInput) -> dict[str, Any]:
    classroom_id = uuid4()
    groups = [group.model_dump(mode="json") for group in data.groups]
    if groups and data.class_id is None:
        raise ApiError(422, "INVALID_INPUT", "小组课堂需要选择已有班级。")
    for attempt in range(3):
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        try:
            with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
                version = connection.execute(text("SELECT activity_id FROM activity_versions WHERE workspace_id=:space AND id=:id"),
                                             {"space": workspace_id, "id": data.version_id}).scalar_one_or_none()
                if version is None:
                    raise ApiError(404, "NOT_FOUND", "活动发布版本不存在。")
                require_object(connection, identity, workspace, version, "activity", "activity.use")
                if data.class_id is not None:
                    if workspace["kind"] == "campus":
                        teaching_class(connection, identity, workspace_id, data.class_id)
                    else:
                        active = connection.execute(text("SELECT active FROM classes WHERE workspace_id=:space AND id=:class FOR SHARE"),
                                                    {"space": workspace_id, "class": data.class_id}).scalar_one_or_none()
                        if active is not True:
                            raise ApiError(403, "FORBIDDEN", "班级不可用。")
                    _roster(connection, workspace_id, data.class_id, groups)
                register_object(connection, identity, workspace, classroom_id, "classroom")
                connection.execute(text("""
                    INSERT INTO classrooms (workspace_id, id, version_id, class_id, title, code, mode, groups, planned_count)
                    VALUES (:space, :id, :version, :class, :title, :code, :mode, CAST(:groups AS jsonb), :planned)
                """), {"space": workspace_id, "id": classroom_id, "version": data.version_id, "class": data.class_id,
                       "title": data.title, "code": code, "mode": "group" if groups else "individual" if data.class_id else "quick",
                       "groups": json.dumps(groups), "planned": 0 if data.class_id else None})
                _event(connection, workspace_id, identity.account_id, "classroom.prepared", classroom_id)
            return {"id": classroom_id, "code": code, "state": "prepared", "revision": 1}
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != "23505" or attempt == 2:
                raise ApiError(409, "CONFLICT", "课堂创建未完成，请重试。") from None
    raise ApiError(503, "SERVICE_UNAVAILABLE", "课堂创建暂不可用。")


def list_classrooms(engine: Engine, identity: StaffIdentity, workspace_id: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要教学权限。")
        rows = connection.execute(text("""
            SELECT c.id, c.title, c.state, c.revision, c.mode, c.planned_count, c.code, c.created_at,
              c.data_epoch,c.ended_at,c.records_deleted_at,c.records_cleaned_at
            FROM classrooms c JOIN authorization_objects o ON o.workspace_id=c.workspace_id AND o.id=c.id
            LEFT JOIN object_grants g ON g.workspace_id=c.workspace_id AND g.object_id=c.id AND g.account_id=:actor
            WHERE c.workspace_id=:space AND o.active AND (o.owner_id=:actor OR (g.active AND 'classroom.read'=ANY(g.capabilities)))
              AND (CAST(:cursor AS uuid) IS NULL OR c.id>CAST(:cursor AS uuid)) ORDER BY c.id LIMIT 51
        """), {"space": workspace_id, "actor": identity.account_id, "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows])


def classroom_detail(engine: Engine, identity: StaffIdentity, workspace_id: UUID, classroom_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_object(connection, identity, workspace, classroom_id, "classroom", "classroom.read")
        return require_classroom(connection, workspace_id, classroom_id)


def change_state(engine: Engine, identity: StaffIdentity, workspace_id: UUID, classroom_id: UUID, data: StateInput) -> None:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_object(connection, identity, workspace, classroom_id, "classroom", "classroom.manage")
        # Membership edits take the exclusive space lock, so assignment facts stay stable in this transaction.
        visible = connection.execute(text("SELECT class_id FROM classrooms WHERE workspace_id=:space AND id=:id"),
                                     {"space": workspace_id, "id": classroom_id}).scalar_one_or_none()
        if visible is not None and workspace["kind"] == "campus":
            teaching_class(connection, identity, workspace_id, visible)
        classroom = require_classroom(connection, workspace_id, classroom_id, write=True)
        if classroom["revision"] != data.expected_revision:
            raise ApiError(409, "REVISION_CONFLICT", "课堂状态已变化，请刷新后操作。")
        allowed = {"prepared": {"open", "ended"}, "open": {"paused", "ended"}, "paused": {"open", "ended"}, "ended": set()}
        if data.state not in allowed[classroom["state"]]:
            raise ApiError(409, "INVALID_STATE", "该课堂状态不能执行此操作，已结束课堂不能重新开放。")
        planned_count = classroom["planned_count"]
        if classroom["state"] == "prepared" and data.state == "open" and classroom["class_id"] is not None:
            rows = _roster(connection, workspace_id, classroom["class_id"], classroom["groups"])
            for row in rows:
                connection.execute(text("""
                    INSERT INTO classroom_roster (workspace_id, classroom_id, student_id, display_name, reference, group_name, members)
                    VALUES (:space, :classroom, :student, :name, :reference, :group, :members)
                """), {"space": workspace_id, "classroom": classroom_id, "student": row["id"], "name": row["display_name"],
                       "reference": row["reference"], "group": row["group_name"], "members": row["members"]})
            planned_count = len(rows)
        connection.execute(text("UPDATE classrooms SET state=:state, revision=revision+1, planned_count=:planned, "
                                "ended_at=CASE WHEN :state='ended' THEN now() ELSE ended_at END "
                                "WHERE workspace_id=:space AND id=:id"),
                           {"space": workspace_id, "id": classroom_id, "state": data.state, "planned": planned_count})
        _event(connection, workspace_id, identity.account_id, f"classroom.{data.state}", classroom_id)


def participant_lock(connection: Connection, workspace_id: UUID, classroom_id: UUID, kind: str, actor_id: UUID) -> None:
    """Serialize only one participant's join/retry; distinct students never share this lock."""
    value = f"{workspace_id}:{classroom_id}:{kind}:{actor_id}".encode()
    key = int.from_bytes(hashlib.sha256(value).digest()[:8], signed=True)
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def eligible(connection: Connection, workspace_id: UUID, classroom: dict[str, Any], kind: str, actor_id: UUID) -> None:
    resource = connection.execute(text("SELECT active FROM authorization_objects WHERE workspace_id=:space AND id=:id FOR SHARE"),
                                  {"space": workspace_id, "id": classroom["id"]}).scalar_one_or_none()
    if resource is not True:
        raise ApiError(403, "FORBIDDEN", "课堂访问已撤销。")
    if kind == "guest":
        belongs = connection.execute(text("SELECT classroom_id FROM classroom_guests WHERE workspace_id=:space AND id=:id AND active"),
                                     {"space": workspace_id, "id": actor_id}).scalar_one_or_none()
        if classroom["mode"] != "quick" or belongs != classroom["id"]:
            raise ApiError(403, "FORBIDDEN", "访客身份只适用于进入的快速课堂。")
        return
    if classroom["class_id"] is not None:
        class_id = connection.execute(text("SELECT class_id FROM students WHERE workspace_id=:space AND id=:id AND active"),
                                      {"space": workspace_id, "id": actor_id}).scalar_one_or_none()
        active = connection.execute(text("SELECT active FROM classes WHERE workspace_id=:space AND id=:class FOR SHARE"),
                                    {"space": workspace_id, "class": classroom["class_id"]}).scalar_one_or_none()
        if class_id != classroom["class_id"] or active is not True:
            raise ApiError(403, "FORBIDDEN", "你已不属于该有效班级，不能继续新写入。")
    if classroom["mode"] == "group":
        recorder = connection.execute(text("SELECT student_id FROM classroom_roster WHERE workspace_id=:space "
                                           "AND classroom_id=:classroom AND student_id=:actor"),
                                      {"space": workspace_id, "classroom": classroom["id"], "actor": actor_id}).scalar_one_or_none()
        if recorder is None:
            raise ApiError(403, "FORBIDDEN", "小组课堂由指定记录员保存和提交，请联系教师。")
