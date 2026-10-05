import hashlib
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from openform.errors import ApiError
from openform.identity.context import StaffIdentity, require_instance, set_context, verify_identity
from openform.identity.schemas import LoginInput, RegistrationInput
from openform.identity.security import hash_password, new_token, token_digest, verify_password


def consume_rate(engine: Engine, key: str, *, limit: int = 10, seconds: int = 300) -> None:
    bucket = hashlib.sha256(key.encode()).hexdigest()
    with engine.begin() as connection:
        count = connection.execute(text("""
            INSERT INTO auth_limits (bucket, window_start, count) VALUES (:bucket, now(), 1)
            ON CONFLICT (bucket) DO UPDATE SET
              count=CASE WHEN auth_limits.window_start < now() - :seconds * interval '1 second'
                THEN 1 ELSE auth_limits.count+1 END,
              window_start=CASE WHEN auth_limits.window_start < now() - :seconds * interval '1 second'
                THEN now() ELSE auth_limits.window_start END
            RETURNING count
        """), {"bucket": bucket, "seconds": seconds}).scalar_one()
    if count > limit:
        raise ApiError(429, "RATE_LIMITED", "验证次数过多，请稍后重试。", retryable=True)


def register(engine: Engine, data: RegistrationInput) -> tuple[UUID, str]:
    password = hash_password(data.password)
    account_id, workspace_id = uuid4(), uuid4()
    token = new_token()
    try:
        with engine.begin() as connection:
            require_instance(connection)
            connection.execute(text("INSERT INTO accounts (id, login, display_name, password_hash) "
                                    "VALUES (:id, :login, :name, :password)"),
                               {"id": account_id, "login": data.login, "name": data.display_name, "password": password})
            set_context(connection, account_id=account_id, workspace_id=workspace_id)
            connection.execute(text("INSERT INTO workspaces (id, name, kind, owner_id) "
                                    "VALUES (:id, '个人空间', 'personal', :owner)"), {"id": workspace_id, "owner": account_id})
            connection.execute(text("INSERT INTO memberships (workspace_id, account_id, is_teacher, is_admin) "
                                    "VALUES (:workspace, :account, true, true)"),
                               {"workspace": workspace_id, "account": account_id})
            connection.execute(text("INSERT INTO auth_sessions (token_digest, account_id, auth_epoch, expires_at) "
                                    "VALUES (:digest, :account, 1, now()+interval '12 hours')"),
                               {"digest": token_digest(token), "account": account_id})
    except IntegrityError:
        raise ApiError(409, "INVALID_INPUT", "暂时无法创建账号，请检查登录名或尝试登录。") from None
    return account_id, token


def login(engine: Engine, data: LoginInput) -> str:
    consume_rate(engine, f"login:{data.login}")
    with engine.connect() as connection:
        require_instance(connection)
        account = connection.execute(text("SELECT * FROM accounts WHERE login=:login"),
                                     {"login": data.login}).mappings().one_or_none()
    valid = verify_password(data.password, account["password_hash"] if account else None)
    if not account or not account["active"] or not valid:
        raise ApiError(401, "UNAUTHENTICATED", "登录名或密码有误。")
    token = new_token()
    with engine.begin() as connection:
        require_instance(connection)
        current = connection.execute(text("SELECT active, auth_epoch FROM accounts WHERE id=:id FOR SHARE"),
                                     {"id": account["id"]}).mappings().one()
        if not current["active"] or current["auth_epoch"] != account["auth_epoch"]:
            raise ApiError(401, "UNAUTHENTICATED", "账号状态已变化，请重新登录。")
        connection.execute(text("INSERT INTO auth_sessions (token_digest, account_id, auth_epoch, expires_at) "
                                "VALUES (:digest, :account, :epoch, now()+interval '12 hours')"),
                           {"digest": token_digest(token), "account": account["id"], "epoch": account["auth_epoch"]})
    return token


def identify(engine: Engine, token: str) -> StaffIdentity:
    digest = token_digest(token)
    with engine.begin() as connection:
        require_instance(connection)
        result = connection.execute(text("""
            SELECT a.id, a.display_name, a.auth_epoch FROM auth_sessions s
            JOIN accounts a ON a.id=s.account_id
            WHERE s.token_digest=:digest AND NOT s.revoked AND s.expires_at > now()
              AND a.active AND a.auth_epoch=s.auth_epoch
        """), {"digest": digest}).mappings().one_or_none()
    if result is None:
        raise ApiError(401, "UNAUTHENTICATED", "会话已失效，请重新登录。")
    return StaffIdentity(result["id"], result["auth_epoch"], digest, result["display_name"])


def list_workspaces(engine: Engine, identity: StaffIdentity) -> list[dict[str, Any]]:
    with engine.begin() as connection:
        require_instance(connection)
        verify_identity(connection, identity)
        set_context(connection, account_id=identity.account_id)
        rows = connection.execute(text("""
            SELECT w.id, w.name, w.kind, w.active AND m.active AS active, m.is_teacher, m.is_admin
            FROM memberships m JOIN workspaces w ON w.id=m.workspace_id
            WHERE m.account_id=:account ORDER BY w.kind DESC, w.name, w.id
        """), {"account": identity.account_id}).mappings().all()
        return [dict(row) for row in rows]


def logout(engine: Engine, identity: StaffIdentity) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE auth_sessions SET revoked=true WHERE token_digest=:digest"),
                           {"digest": identity.session_digest})
