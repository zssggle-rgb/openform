from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from openform.classrooms.service import require_classroom
from openform.errors import ApiError
from openform.identity.context import require_instance
from openform.identity.security import new_token, token_digest

GUEST_COOKIE = "openform_guest"


@dataclass(frozen=True)
class GuestIdentity:
    workspace_id: UUID
    guest_id: UUID
    session_digest: str


def guest_context(connection: Connection, workspace_id: UUID) -> dict[str, Any]:
    require_instance(connection)
    connection.execute(text("SELECT set_config('openform.workspace_id', :space, true), "
                            "set_config('openform.account_id', '', true)"), {"space": str(workspace_id)})
    workspace = connection.execute(text("SELECT id, name, active FROM workspaces WHERE id=:space FOR SHARE"),
                                   {"space": workspace_id}).mappings().one_or_none()
    if workspace is None or not workspace["active"]:
        raise ApiError(401, "UNAUTHENTICATED", "课堂身份已失效，请重新进入。")
    return dict(workspace)


@contextmanager
def guest_transaction(engine: Engine, identity: GuestIdentity) -> Iterator[tuple[Connection, dict[str, Any], dict[str, Any]]]:
    with engine.begin() as connection:
        workspace = guest_context(connection, identity.workspace_id)
        guest = connection.execute(text("SELECT * FROM classroom_guests WHERE workspace_id=:space AND id=:id FOR SHARE"),
                                   {"space": identity.workspace_id, "id": identity.guest_id}).mappings().one_or_none()
        session = connection.execute(text("SELECT guest_id, revoked, expires_at>now() AS valid FROM guest_sessions "
                                          "WHERE workspace_id=:space AND token_digest=:digest FOR SHARE"),
                                     {"space": identity.workspace_id, "digest": identity.session_digest}).mappings().one_or_none()
        if (guest is None or not guest["active"] or session is None or session["guest_id"] != identity.guest_id
                or session["revoked"] or not session["valid"]):
            raise ApiError(401, "UNAUTHENTICATED", "课堂身份已失效，请重新进入。")
        yield connection, workspace, dict(guest)


def identify_guest(engine: Engine, token: str) -> GuestIdentity:
    digest = token_digest(token)
    with engine.begin() as connection:
        require_instance(connection)
        space = connection.execute(text("SELECT workspace_id FROM locate_guest_session(:digest)"), {"digest": digest}).scalar_one_or_none()
        if space is None:
            raise ApiError(401, "UNAUTHENTICATED", "课堂身份已失效，请重新进入。")
        guest_context(connection, space)
        actor = connection.execute(text("SELECT guest_id FROM guest_sessions WHERE workspace_id=:space AND token_digest=:digest"),
                                   {"space": space, "digest": digest}).scalar_one()
    identity = GuestIdentity(space, actor, digest)
    with guest_transaction(engine, identity):
        pass
    return identity


def enter_guest(engine: Engine, code: str, display_name: str) -> str:
    token, guest_id = new_token(), uuid4()
    with engine.begin() as connection:
        require_instance(connection)
        locator = connection.execute(text("SELECT workspace_id, classroom_id FROM locate_classroom(:code)"),
                                     {"code": code}).mappings().one_or_none()
        if locator is None:
            raise ApiError(404, "NOT_FOUND", "课堂码错误或课堂已不可访问。")
        space = locator["workspace_id"]
        guest_context(connection, space)
        classroom = require_classroom(connection, space, locator["classroom_id"])
        if classroom["mode"] != "quick" or classroom["state"] != "open":
            raise ApiError(403, "CLASSROOM_NOT_OPEN", "该课堂不能以快速身份进入，请按教师要求验证个人码或等待开课。")
        connection.execute(text("INSERT INTO classroom_guests (workspace_id, classroom_id, id, display_name) "
                                "VALUES (:space, :classroom, :id, :name)"),
                           {"space": space, "classroom": classroom["id"], "id": guest_id, "name": display_name})
        connection.execute(text("INSERT INTO guest_sessions (workspace_id, token_digest, guest_id, expires_at) "
                                "VALUES (:space, :digest, :id, now()+interval '12 hours')"),
                           {"space": space, "digest": token_digest(token), "id": guest_id})
    return token


def guest_session(engine: Engine, identity: GuestIdentity) -> dict[str, Any]:
    with guest_transaction(engine, identity) as (connection, workspace, guest):
        classroom = require_classroom(connection, identity.workspace_id, guest["classroom_id"])
        return {"workspace_id": identity.workspace_id, "guest_id": identity.guest_id, "display_name": guest["display_name"],
                "workspace_name": workspace["name"], "classroom_id": classroom["id"], "classroom_title": classroom["title"],
                "classroom_state": classroom["state"]}


def logout_guest(engine: Engine, identity: GuestIdentity) -> None:
    with guest_transaction(engine, identity) as (connection, _, _):
        connection.execute(text("UPDATE guest_sessions SET revoked=true WHERE workspace_id=:space AND token_digest=:digest"),
                           {"space": identity.workspace_id, "digest": identity.session_digest})
