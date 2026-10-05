from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from openform.errors import ApiError
from openform.identity.accounts import consume_rate
from openform.identity.context import (
    StaffIdentity,
    require_admin,
    require_instance,
    set_context,
    verify_identity,
    workspace_transaction,
)
from openform.identity.roster import _event
from openform.identity.schemas import InviteInput, MemberInput
from openform.identity.security import new_token, token_digest


def list_members(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                 cursor: UUID | None = None, query: str = "") -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_admin(workspace)
        query = query.strip()
        if len(query) > 80:
            raise ApiError(422, "INVALID_INPUT", "成员搜索不超过 80 个字符。")
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = connection.execute(text("""
            SELECT m.account_id, a.display_name, a.login, m.is_teacher, m.is_admin, m.active, m.auth_epoch
            FROM memberships m JOIN accounts a ON a.id=m.account_id
            WHERE m.workspace_id=:workspace AND (CAST(:cursor AS uuid) IS NULL OR a.id>CAST(:cursor AS uuid))
              AND (a.display_name ILIKE :pattern OR a.login ILIKE :pattern)
            ORDER BY a.id LIMIT 51
        """), {"workspace": workspace_id, "cursor": cursor, "pattern": pattern}).mappings().all()
        return {"items": [dict(row) for row in rows[:50]],
                "next_cursor": str(rows[49]["account_id"]) if len(rows) > 50 else None}


def list_invites(engine: Engine, identity: StaffIdentity, workspace_id: UUID) -> list[dict[str, Any]]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_admin(workspace)
        return [dict(row) for row in connection.execute(text("""
            SELECT id, is_teacher, is_admin, target_login, expires_at, active,
              used_by IS NOT NULL AS accepted FROM staff_invites
            WHERE workspace_id=:workspace
            ORDER BY (active AND used_by IS NULL AND expires_at>now()) DESC, expires_at DESC, id LIMIT 100
        """), {"workspace": workspace_id}).mappings().all()]


def change_member(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                  account_id: UUID, data: MemberInput) -> None:
    with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
        require_admin(workspace)
        if workspace["kind"] == "personal":
            raise ApiError(403, "FORBIDDEN", "个人空间的拥有者身份不能由成员管理修改。")
        member = connection.execute(text("SELECT * FROM memberships WHERE workspace_id=:workspace "
                                         "AND account_id=:account FOR UPDATE"),
                                    {"workspace": workspace_id, "account": account_id}).mappings().one_or_none()
        if member is None:
            raise ApiError(404, "NOT_FOUND", "成员不存在。")
        if member["auth_epoch"] != data.expected_epoch:
            raise ApiError(409, "REVISION_CONFLICT", "成员信息已被其他操作更新，请刷新后重试。")
        if member["active"] and member["is_admin"] and (not data.active or not data.is_admin):
            admins = connection.execute(text("SELECT count(*) FROM memberships WHERE workspace_id=:workspace "
                                             "AND active AND is_admin"), {"workspace": workspace_id}).scalar_one()
            if admins == 1:
                raise ApiError(409, "STATE_CONFLICT", "至少保留一位有效学校管理员。")
        connection.execute(text("UPDATE memberships SET active=:active, is_teacher=:teacher, is_admin=:admin, "
                                "auth_epoch=auth_epoch+1 WHERE workspace_id=:workspace AND account_id=:account"),
                           {"active": data.active, "teacher": data.is_teacher, "admin": data.is_admin,
                            "workspace": workspace_id, "account": account_id})
        if not data.active or not data.is_teacher:
            connection.execute(text("UPDATE object_grants SET active=false,capabilities='{}',revision=revision+1 "
                                    "WHERE workspace_id=:workspace AND account_id=:account AND active"),
                               {"workspace": workspace_id, "account": account_id})
        if not data.active or member["is_teacher"] != data.is_teacher or member["is_admin"] != data.is_admin:
            connection.execute(text("UPDATE memberships SET session_valid_after=clock_timestamp() "
                                    "WHERE workspace_id=:workspace AND account_id=:account"),
                               {"workspace": workspace_id, "account": account_id})
        _event(connection, workspace_id, identity.account_id, "member.changed", account_id)


def create_invite(engine: Engine, identity: StaffIdentity, workspace_id: UUID,
                  data: InviteInput) -> dict[str, Any]:
    token, invite_id = new_token(), uuid4()
    with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
        require_admin(workspace)
        if workspace["kind"] != "campus":
            raise ApiError(403, "FORBIDDEN", "个人空间不开放校园成员邀请。")
        count = connection.execute(text("SELECT count(*) FROM staff_invites WHERE workspace_id=:workspace "
                                        "AND active AND used_by IS NULL AND expires_at>now()"),
                                   {"workspace": workspace_id}).scalar_one()
        if count >= 100:
            raise ApiError(409, "STATE_CONFLICT", "待接受邀请已达上限，请先撤销不用的邀请。")
        expires = insert_invite(connection, workspace_id, invite_id, token, data)
    return {"id": invite_id, "token": token, "expires_at": expires}


def insert_invite(connection: Connection, workspace_id: UUID, invite_id: UUID,
                  token: str, data: InviteInput) -> Any:
    return connection.execute(text("""
        INSERT INTO staff_invites (workspace_id, id, token_digest, is_teacher, is_admin, target_login, expires_at)
        VALUES (:workspace, :id, :digest, :teacher, :admin, :target, now()+interval '7 days')
        RETURNING expires_at
    """), {"workspace": workspace_id, "id": invite_id, "digest": token_digest(token),
           "teacher": data.is_teacher, "admin": data.is_admin,
           "target": data.target_login.lower() if data.target_login else None}).scalar_one()


def revoke_invite(engine: Engine, identity: StaffIdentity, workspace_id: UUID, invite_id: UUID) -> None:
    with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
        require_admin(workspace)
        result = connection.execute(text("UPDATE staff_invites SET active=false WHERE workspace_id=:workspace AND id=:id"),
                                    {"workspace": workspace_id, "id": invite_id})
        if result.rowcount != 1:
            raise ApiError(404, "NOT_FOUND", "邀请不存在。")


def accept_invite(engine: Engine, identity: StaffIdentity, token: str) -> UUID:
    digest = token_digest(token)
    consume_rate(engine, f"invite:{identity.account_id}")
    with engine.begin() as connection:
        found = connection.execute(text("SELECT workspace_id FROM locate_invite(:digest)"),
                                   {"digest": digest}).scalar_one_or_none()
    if found is None:
        raise ApiError(403, "FORBIDDEN", "邀请已失效，请联系学校管理员。")
    # Accepting the first invite is deliberately separate from member-authorized transactions.
    with engine.begin() as connection:
        require_instance(connection)
        set_context(connection, account_id=identity.account_id, workspace_id=found)
        workspace = connection.execute(text("SELECT active FROM workspaces WHERE id=:workspace FOR UPDATE"),
                                       {"workspace": found}).mappings().one_or_none()
        if not workspace or not workspace["active"]:
            raise ApiError(403, "FORBIDDEN", "学校空间不可用。")
        verify_identity(connection, identity)
        invite = connection.execute(text("SELECT *, expires_at>now() AS valid FROM staff_invites "
                                        "WHERE workspace_id=:workspace AND token_digest=:digest FOR UPDATE"),
                                   {"workspace": found, "digest": digest}).mappings().one_or_none()
        login = connection.execute(text("SELECT login FROM accounts WHERE id=:id"),
                                   {"id": identity.account_id}).scalar_one()
        if (not invite or not invite["active"] or invite["used_by"] or not invite["valid"]
                or invite["target_login"] and invite["target_login"] != login):
            raise ApiError(403, "FORBIDDEN", "邀请不适用于当前账号或已失效。")
        existing = connection.execute(text("SELECT active FROM memberships WHERE workspace_id=:workspace "
                                           "AND account_id=:account FOR UPDATE"),
                                      {"workspace": found, "account": identity.account_id}).mappings().one_or_none()
        if existing is not None:
            raise ApiError(409, "STATE_CONFLICT", "当前账号已存在成员记录，请由管理员处理其状态。")
        connection.execute(text("INSERT INTO memberships (workspace_id, account_id, is_teacher, is_admin) "
                                "VALUES (:workspace, :account, :teacher, :admin)"),
                           {"workspace": found, "account": identity.account_id,
                            "teacher": invite["is_teacher"], "admin": invite["is_admin"]})
        connection.execute(text("UPDATE staff_invites SET used_by=:account WHERE workspace_id=:workspace AND id=:id"),
                           {"account": identity.account_id, "workspace": found, "id": invite["id"]})
    return UUID(str(found))


def preview_invite(engine: Engine, identity: StaffIdentity, token: str) -> dict[str, Any]:
    digest = token_digest(token)
    consume_rate(engine, f"invite-preview:{identity.account_id}", limit=30)
    with engine.begin() as connection:
        require_instance(connection)
        verify_identity(connection, identity)
        workspace_id = connection.execute(text("SELECT workspace_id FROM locate_invite(:digest)"),
                                          {"digest": digest}).scalar_one_or_none()
        if workspace_id is None:
            raise ApiError(403, "FORBIDDEN", "邀请已失效，请联系学校管理员。")
        set_context(connection, account_id=identity.account_id, workspace_id=workspace_id)
        invitation = connection.execute(text("""
            SELECT w.id, w.name, i.is_teacher, i.is_admin FROM staff_invites i
            JOIN workspaces w ON w.id=i.workspace_id JOIN accounts a ON a.id=:account
            WHERE i.workspace_id=:workspace AND i.token_digest=:digest AND i.active
              AND i.used_by IS NULL AND i.expires_at>now() AND w.active
              AND (i.target_login IS NULL OR i.target_login=a.login)
        """), {"workspace": workspace_id, "digest": digest, "account": identity.account_id}).mappings().one_or_none()
        if invitation is None:
            raise ApiError(403, "FORBIDDEN", "邀请不适用于当前账号或已失效。")
        return dict(invitation)
