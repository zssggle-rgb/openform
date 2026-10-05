import hashlib
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from openform.errors import ApiError
from openform.identity.accounts import consume_rate
from openform.identity.context import StaffIdentity, require_instance, workspace_transaction
from openform.identity.roster import _event, require_student
from openform.identity.security import new_token, token_digest

STUDENT_COOKIE = "openform_student"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class StudentIdentity:
    workspace_id: UUID
    student_id: UUID
    auth_epoch: int
    session_digest: str


def _student_context(connection: Connection, workspace_id: UUID) -> None:
    connection.execute(text("SELECT set_config('openform.account_id', '', true), "
                            "set_config('openform.workspace_id', :workspace, true)"), {"workspace": str(workspace_id)})


def _workspace(connection: Connection, workspace_id: UUID) -> dict[str, Any]:
    workspace = connection.execute(text("SELECT id, name, active FROM workspaces WHERE id=:id FOR SHARE"),
                                   {"id": workspace_id}).mappings().one_or_none()
    if not workspace or not workspace["active"]:
        raise ApiError(401, "UNAUTHENTICATED", "学生身份已失效，请联系教师。")
    return dict(workspace)


def _verify(connection: Connection, identity: StudentIdentity, *, session_write: bool = False) -> dict[str, Any]:
    student = connection.execute(text("SELECT id, reference, display_name, active, auth_epoch FROM students "
                                      "WHERE workspace_id=:space AND id=:id FOR SHARE"),
                                 {"space": identity.workspace_id, "id": identity.student_id}).mappings().one_or_none()
    session_lock = "UPDATE" if session_write else "SHARE"
    session = connection.execute(text("SELECT student_id, auth_epoch, revoked, expires_at>now() AS valid "
                                      f"FROM student_sessions WHERE workspace_id=:space AND token_digest=:digest FOR {session_lock}"),
                                 {"space": identity.workspace_id, "digest": identity.session_digest}).mappings().one_or_none()
    if (not student or not student["active"] or student["auth_epoch"] != identity.auth_epoch
            or not session or session["student_id"] != identity.student_id or session["auth_epoch"] != identity.auth_epoch
            or session["revoked"] or not session["valid"]):
        raise ApiError(401, "UNAUTHENTICATED", "学生身份已失效，请重新验证个人进入码。")
    return dict(student)


@contextmanager
def student_transaction(engine: Engine, identity: StudentIdentity, *, session_write: bool = False) -> Iterator[tuple[Connection, dict[str, Any], dict[str, Any]]]:
    with engine.begin() as connection:
        require_instance(connection)
        _student_context(connection, identity.workspace_id)
        workspace = _workspace(connection, identity.workspace_id)
        student = _verify(connection, identity, session_write=session_write)
        yield connection, workspace, student


def identify_student(engine: Engine, token: str) -> StudentIdentity:
    digest = token_digest(token)
    with engine.begin() as connection:
        require_instance(connection)
        workspace_id = connection.execute(text("SELECT workspace_id FROM locate_student_session(:digest)"),
                                          {"digest": digest}).scalar_one_or_none()
        if workspace_id is None:
            raise ApiError(401, "UNAUTHENTICATED", "学生会话已失效，请重新验证个人进入码。")
        _student_context(connection, workspace_id)
        _workspace(connection, workspace_id)
        session = connection.execute(text("SELECT student_id, auth_epoch FROM student_sessions "
                                          "WHERE workspace_id=:space AND token_digest=:digest"),
                                     {"space": workspace_id, "digest": digest}).mappings().one()
        identity = StudentIdentity(workspace_id, session["student_id"], session["auth_epoch"], digest)
        _verify(connection, identity)
        return identity


def exchange_code(engine: Engine, code: str) -> str:
    digest = hashlib.sha256(code.encode()).hexdigest()
    consume_rate(engine, f"student-code:{digest}", limit=40)
    token = new_token()
    with engine.begin() as connection:
        require_instance(connection)
        workspace_id = connection.execute(text("SELECT workspace_id FROM locate_student_code(:digest)"),
                                          {"digest": digest}).scalar_one_or_none()
        if workspace_id is None:
            raise ApiError(401, "UNAUTHENTICATED", "个人进入码错误或已失效，请联系教师。")
        _student_context(connection, workspace_id)
        _workspace(connection, workspace_id)
        student = connection.execute(text("SELECT id, auth_epoch FROM students WHERE workspace_id=:space "
                                          "AND code_digest=:digest AND active AND code_expires_at>now() FOR SHARE"),
                                     {"space": workspace_id, "digest": digest}).mappings().one_or_none()
        if student is None:
            raise ApiError(401, "UNAUTHENTICATED", "个人进入码已变化，请使用新码验证。")
        connection.execute(text("INSERT INTO student_sessions (workspace_id, token_digest, student_id, auth_epoch, expires_at) "
                                "VALUES (:space, :digest, :student, :epoch, now()+interval '12 hours')"),
                           {"space": workspace_id, "digest": token_digest(token), "student": student["id"], "epoch": student["auth_epoch"]})
    return token


def issue_code(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
               student_id: UUID, expected_epoch: int) -> dict[str, Any]:
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(16))
    with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
        student = require_student(connection, identity, workspace, student_id)
        if not student["active"]:
            raise ApiError(403, "FORBIDDEN", "该学生条目已停用，不能发放进入码。")
        if student["auth_epoch"] != expected_epoch:
            raise ApiError(409, "REVISION_CONFLICT", "个人进入码已被其他操作调整，请刷新后重试。")
        result = connection.execute(text("UPDATE students SET code_digest=:digest, code_expires_at=now()+interval '30 days', "
                                         "auth_epoch=auth_epoch+1 WHERE workspace_id=:space AND id=:id RETURNING code_expires_at, auth_epoch"),
                                    {"space": workspace_id, "id": student_id, "digest": hashlib.sha256(code.encode()).hexdigest()}).mappings().one()
        _event(connection, workspace_id, identity.account_id, "student.code-issued", student_id)
    return {"student_id": student_id, "code": "-".join(code[index:index+4] for index in range(0, 16, 4)),
            "expires_at": result["code_expires_at"], "auth_epoch": result["auth_epoch"]}


def revoke_code(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                student_id: UUID, expected_epoch: int) -> None:
    with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
        student = require_student(connection, identity, workspace, student_id)
        if student["auth_epoch"] != expected_epoch:
            raise ApiError(409, "REVISION_CONFLICT", "个人进入码已变化，请刷新后重试。")
        connection.execute(text("UPDATE students SET code_digest=NULL, code_expires_at=NULL, auth_epoch=auth_epoch+1 "
                                "WHERE workspace_id=:space AND id=:id"), {"space": workspace_id, "id": student_id})
        _event(connection, workspace_id, identity.account_id, "student.code-revoked", student_id)


def student_session(engine: Engine, identity: StudentIdentity) -> dict[str, Any]:
    with student_transaction(engine, identity) as (_, workspace, student):
        return {"workspace_id": workspace["id"], "workspace_name": workspace["name"],
                "student_id": student["id"], "display_name": student["display_name"], "reference": student["reference"]}


def logout_student(engine: Engine, identity: StudentIdentity) -> None:
    with student_transaction(engine, identity, session_write=True) as (connection, _, __):
        connection.execute(text("UPDATE student_sessions SET revoked=true WHERE workspace_id=:space AND token_digest=:digest"),
                           {"space": identity.workspace_id, "digest": identity.session_digest})
