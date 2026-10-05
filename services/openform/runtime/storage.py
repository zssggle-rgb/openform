import hashlib
import json
import secrets
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from openform.errors import ApiError
from openform.identity.context import require_instance
from openform.runtime.packages import RuntimePackage


def store_package(connection: Connection, workspace_id: UUID, package: RuntimePackage) -> None:
    """Only a caller's already-authorized business transaction can register a package."""
    connection.execute(text("""
        INSERT INTO runtime_packages (workspace_id, digest, manifest, document, policy)
        VALUES (:space, :digest, CAST(:manifest AS jsonb), :document, :policy)
        ON CONFLICT (workspace_id, digest) DO NOTHING
    """), {"space": workspace_id, "digest": package.digest,
           "manifest": json.dumps(package.manifest, ensure_ascii=False), "document": package.document, "policy": package.policy})


def issue_ticket(connection: Connection, workspace_id: UUID, package_digest: str, *, runtime_origin: str) -> str:
    """Document access only; it is never an account, student or submission credential."""
    token = secrets.token_urlsafe(32)
    connection.execute(text("""
        INSERT INTO runtime_tickets (workspace_id, token_digest, package_digest, expires_at)
        VALUES (:space, :digest, :package, now()+interval '1 hour')
    """), {"space": workspace_id, "digest": hashlib.sha256(token.encode("ascii")).hexdigest(), "package": package_digest})
    return f"{runtime_origin}/p/{token}"


def read_document(engine: Engine, token: str) -> tuple[str, str]:
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    with engine.begin() as connection:
        require_instance(connection)
        workspace_id = connection.execute(text("SELECT workspace_id FROM locate_runtime_ticket(:digest)"),
                                          {"digest": digest}).scalar_one_or_none()
        if workspace_id is None:
            raise ApiError(404, "NOT_FOUND", "活动页面不可用，请从课堂入口重新打开。")
        connection.execute(text("SELECT set_config('openform.workspace_id', :space, true), "
                                "set_config('openform.account_id', '', true)"), {"space": str(workspace_id)})
        active = connection.execute(text("SELECT active FROM workspaces WHERE id=:space FOR SHARE"),
                                    {"space": workspace_id}).scalar_one_or_none()
        if active is not True:
            raise ApiError(404, "NOT_FOUND", "活动页面不可用，请从课堂入口重新打开。")
        ticket = connection.execute(text("SELECT package_digest FROM runtime_tickets WHERE workspace_id=:space "
                                         "AND token_digest=:digest AND NOT revoked AND expires_at>now() FOR SHARE"),
                                    {"space": workspace_id, "digest": digest}).scalar_one_or_none()
        if ticket is None:
            raise ApiError(404, "NOT_FOUND", "活动页面不可用，请从课堂入口重新打开。")
        package = connection.execute(text("SELECT document, policy FROM runtime_packages WHERE workspace_id=:space AND digest=:digest"),
                                     {"space": workspace_id, "digest": ticket}).mappings().one_or_none()
        if package is None:
            raise ApiError(404, "NOT_FOUND", "活动页面不可用，请从课堂入口重新打开。")
        return str(package["document"]), str(package["policy"])
