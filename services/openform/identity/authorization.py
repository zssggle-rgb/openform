"""Capabilities over locked server facts; object creation stays in business transactions."""
from typing import Any, Literal
from uuid import UUID

from openform_contracts.permissions import AccessFacts, permits
from pydantic import Field
from sqlalchemy import Connection, Engine, text

from openform.errors import ApiError
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.roster import _event, _page
from openform.identity.schemas import Input

ObjectKind = Literal["activity", "classroom", "archive"]
CAPABILITIES = {
    "activity": frozenset({"activity.read", "activity.edit", "activity.publish", "activity.use", "resource.publish"}),
    "classroom": frozenset({"classroom.read", "classroom.manage", "records.read", "records.delete", "analysis.create", "export.create"}),
    "archive": frozenset({"records.read", "export.create"}),
}


class GrantInput(Input):
    capabilities: list[str] = Field(max_length=10)
    expected_revision: int = Field(ge=0)


def register_object(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any],
                    object_id: UUID, kind: ObjectKind) -> None:
    """Called after workspace_transaction, in the same transaction as the real object."""
    if kind not in CAPABILITIES or not workspace["is_teacher"]:
        raise ApiError(403, "FORBIDDEN", "需要当前空间的教学权限。")
    connection.execute(text("INSERT INTO authorization_objects (workspace_id, id, kind, owner_id) "
                            "VALUES (:space, :id, :kind, :owner)"),
                       {"space": workspace["id"], "id": object_id, "kind": kind, "owner": identity.account_id})


def require_object(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any],
                   object_id: UUID, kind: ObjectKind, action: str) -> dict[str, Any]:
    resource = connection.execute(text("SELECT * FROM authorization_objects WHERE workspace_id=:space "
                                       "AND id=:id AND kind=:kind FOR SHARE"),
                                  {"space": workspace["id"], "id": object_id, "kind": kind}).mappings().one_or_none()
    if resource is None:
        raise ApiError(404, "NOT_FOUND", "目标对象不存在。")
    grant = connection.execute(text("SELECT capabilities, active FROM object_grants WHERE workspace_id=:space "
                                    "AND object_id=:object AND account_id=:account FOR SHARE"),
                               {"space": workspace["id"], "object": object_id, "account": identity.account_id}).mappings().one_or_none()
    facts = AccessFacts(actor_id=str(identity.account_id), actor_kind="staff", workspace_id=str(workspace["id"]),
                        target_workspace_id=str(resource["workspace_id"]), workspace_active=workspace["active"], membership_active=True,
                        roles=frozenset(role for role, valid in (("teacher", workspace["is_teacher"]), ("admin", workspace["is_admin"])) if valid),
                        personal_owner=workspace["kind"] == "personal" and workspace["owner_id"] == identity.account_id,
                        owner_id=str(resource["owner_id"]),
                        grants=frozenset(grant["capabilities"]) if grant and grant["active"] else frozenset())
    if not resource["active"] or action not in CAPABILITIES.get(kind, ()) or not permits(action, facts):
        raise ApiError(403, "FORBIDDEN", "你没有该对象的操作权限。")
    return dict(resource)


def _owned(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], object_id: UUID) -> dict[str, Any]:
    resource = connection.execute(text("SELECT * FROM authorization_objects WHERE workspace_id=:space AND id=:id FOR SHARE"),
                                  {"space": workspace["id"], "id": object_id}).mappings().one_or_none()
    if resource is None:
        raise ApiError(404, "NOT_FOUND", "目标对象不存在。")
    if not resource["active"] or not workspace["is_teacher"] or resource["owner_id"] != identity.account_id:
        raise ApiError(403, "FORBIDDEN", "只有对象所属教师可以调整授权。")
    return dict(resource)


def list_grants(engine: Engine, identity: StaffIdentity, workspace_id: UUID, object_id: UUID,
                cursor: UUID | None = None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        _owned(connection, identity, workspace, object_id)
        rows = connection.execute(text("""
            SELECT g.account_id, a.display_name, g.capabilities, g.active, g.revision,
              m.active AND a.active AND m.is_teacher AS member_eligible
            FROM object_grants g JOIN accounts a ON a.id=g.account_id
            JOIN memberships m ON m.workspace_id=g.workspace_id AND m.account_id=g.account_id
            WHERE g.workspace_id=:space AND g.object_id=:object
              AND (CAST(:cursor AS uuid) IS NULL OR g.account_id>CAST(:cursor AS uuid)) ORDER BY g.account_id LIMIT 51
        """), {"space": workspace_id, "object": object_id, "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows], "account_id")


def change_grant(engine: Engine, identity: StaffIdentity, workspace_id: UUID, object_id: UUID,
                 account_id: UUID, data: GrantInput) -> None:
    with workspace_transaction(engine, identity, workspace_id, authorization_write=True) as (connection, workspace):
        resource = _owned(connection, identity, workspace, object_id)
        capabilities = sorted(set(data.capabilities))
        if not set(capabilities).issubset(CAPABILITIES[resource["kind"]]):
            raise ApiError(422, "INVALID_INPUT", "授权能力与对象类型不匹配。")
        if account_id == identity.account_id:
            raise ApiError(422, "INVALID_INPUT", "对象所属教师无需给自己授权。")
        eligible = connection.execute(text("SELECT m.active AND m.is_teacher AND a.active FROM memberships m "
                                           "JOIN accounts a ON a.id=m.account_id WHERE m.workspace_id=:space "
                                           "AND m.account_id=:id FOR SHARE OF m, a"),
                                      {"space": workspace_id, "id": account_id}).scalar_one_or_none()
        if eligible is None or capabilities and not eligible:
            raise ApiError(403, "FORBIDDEN", "授权必须指向本空间有效的教师成员。")
        revision = connection.execute(text("SELECT revision FROM object_grants WHERE workspace_id=:space "
                                           "AND object_id=:object AND account_id=:id FOR UPDATE"),
                                      {"space": workspace_id, "object": object_id, "id": account_id}).scalar_one_or_none()
        if (revision or 0) != data.expected_revision:
            raise ApiError(409, "REVISION_CONFLICT", "对象授权已变化，请刷新后重试。")
        connection.execute(text("""
            INSERT INTO object_grants (workspace_id, object_id, account_id, capabilities, active)
            VALUES (:space, :object, :id, :capabilities, :active)
            ON CONFLICT (workspace_id, object_id, account_id) DO UPDATE
              SET capabilities=EXCLUDED.capabilities, active=EXCLUDED.active, revision=object_grants.revision+1
        """), {"space": workspace_id, "object": object_id, "id": account_id, "capabilities": capabilities, "active": bool(capabilities)})
        _event(connection, workspace_id, identity.account_id, "object.grant-changed", object_id)
