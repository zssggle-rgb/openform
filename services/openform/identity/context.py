from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from openform.errors import ApiError


@dataclass(frozen=True)
class StaffIdentity:
    account_id: UUID
    auth_epoch: int
    session_digest: str
    display_name: str


def set_context(connection: Connection, *, account_id: UUID, workspace_id: UUID | None = None) -> None:
    connection.execute(text("SELECT set_config('openform.account_id', :account, true), "
                            "set_config('openform.workspace_id', :workspace, true)"),
                       {"account": str(account_id), "workspace": str(workspace_id) if workspace_id else ""})


def verify_identity(connection: Connection, identity: StaffIdentity) -> None:
    account = connection.execute(text("SELECT active, auth_epoch FROM accounts WHERE id=:id FOR SHARE"),
                                 {"id": identity.account_id}).mappings().one_or_none()
    session = connection.execute(text("SELECT revoked, expires_at > now() AS valid FROM auth_sessions "
                                      "WHERE token_digest=:digest FOR SHARE"),
                                 {"digest": identity.session_digest}).mappings().one_or_none()
    if (not account or not account["active"] or account["auth_epoch"] != identity.auth_epoch
            or not session or session["revoked"] or not session["valid"]):
        raise ApiError(401, "UNAUTHENTICATED", "会话已失效，请重新登录。")


def require_instance(connection: Connection) -> None:
    locked = connection.execute(text("SELECT instance_is_locked()")).scalar_one()
    if locked is not False:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "实例正在维护或等待恢复授权。", retryable=True)


@contextmanager
def workspace_transaction(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                          *, authorization_write: bool = False) -> Iterator[tuple[Connection, dict[str, Any]]]:
    """Space -> account/session -> member locks; SET LOCAL never escapes the transaction."""
    with engine.begin() as connection:
        require_instance(connection)
        set_context(connection, account_id=identity.account_id, workspace_id=workspace_id)
        lock = "UPDATE" if authorization_write else "SHARE"
        workspace = connection.execute(text(f"SELECT * FROM workspaces WHERE id=:id FOR {lock}"),
                                       {"id": workspace_id}).mappings().one_or_none()
        if not workspace or not workspace["active"]:
            raise ApiError(403, "FORBIDDEN", "当前空间不可访问。")
        verify_identity(connection, identity)
        member = connection.execute(text("SELECT * FROM memberships WHERE workspace_id=:workspace "
                                         "AND account_id=:account FOR SHARE"),
                                    {"workspace": workspace_id, "account": identity.account_id}).mappings().one_or_none()
        if not member or not member["active"]:
            raise ApiError(403, "FORBIDDEN", "你已失去该空间的访问权限。")
        session_fresh = connection.execute(text("SELECT created_at>:cutoff FROM auth_sessions WHERE token_digest=:digest"),
                                           {"cutoff": member["session_valid_after"], "digest": identity.session_digest}).scalar_one()
        if not session_fresh:
            raise ApiError(403, "WORKSPACE_SESSION_EXPIRED", "此空间权限已调整，请重新登录；个人空间及其他学校不受影响。")
        yield connection, {**dict(workspace), "is_admin": member["is_admin"], "is_teacher": member["is_teacher"]}


def require_admin(workspace: dict[str, Any]) -> None:
    if not workspace["is_admin"]:
        raise ApiError(403, "FORBIDDEN", "需要当前空间的管理权限。")
