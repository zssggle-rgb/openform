from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Engine, text

from openform.classrooms.service import teaching_class
from openform.errors import ApiError
from openform.identity.context import StaffIdentity, require_admin, workspace_transaction
from openform.identity.roster import _event, _page
from openform.identity.schemas import Input


class TransferInput(Input):
    expected_revision: int = Field(ge=1)
    expected_owner: UUID
    recipient_id: UUID
    confirmed: bool


def list_assets(engine: Engine, identity: StaffIdentity, space: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_admin(workspace)
        if workspace["kind"] != "campus":
            raise ApiError(403, "FORBIDDEN", "资产交接仅用于校园空间。")
        rows = connection.execute(text("""
          SELECT o.id,o.kind,o.owner_id,o.creator_id,o.revision,a.display_name AS owner_name,
            m.active AND m.is_teacher AND a.active AS owner_eligible,coalesce(t.title,c.title,h.title) AS title
          FROM authorization_objects o JOIN accounts a ON a.id=o.owner_id
          JOIN memberships m ON m.workspace_id=o.workspace_id AND m.account_id=o.owner_id
          LEFT JOIN activities t ON t.workspace_id=o.workspace_id AND t.id=o.id
          LEFT JOIN classrooms c ON c.workspace_id=o.workspace_id AND c.id=o.id
          LEFT JOIN classroom_archives h ON h.workspace_id=o.workspace_id AND h.id=o.id
          WHERE o.workspace_id=:space AND o.active
            AND (CAST(:cursor AS uuid) IS NULL OR o.id>CAST(:cursor AS uuid)) ORDER BY o.id LIMIT 51
        """), {"space": space, "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows])


def transfer_asset(engine: Engine, identity: StaffIdentity, space: UUID, object_id: UUID, data: TransferInput) -> None:
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        require_admin(workspace)
        if workspace["kind"] != "campus" or not data.confirmed:
            raise ApiError(422, "CONFIRMATION_REQUIRED", "请明确确认校园资产及新接收教师；旧对象授权将全部撤销。")
        eligible = connection.execute(text("SELECT m.active AND m.is_teacher AND a.active FROM memberships m "
                                           "JOIN accounts a ON a.id=m.account_id WHERE m.workspace_id=:space "
                                           "AND m.account_id=:id FOR SHARE OF m,a"), {"space": space, "id": data.recipient_id}).scalar_one_or_none()
        if eligible is not True:
            raise ApiError(409, "OWNERSHIP_CONFLICT", "接收者必须是本校当前有效教师。原资产未交接。")
        resource = connection.execute(text("SELECT * FROM authorization_objects WHERE workspace_id=:space AND id=:id FOR UPDATE"), {"space": space, "id": object_id}).mappings().one_or_none()
        if resource is None or not resource["active"]:
            raise ApiError(404, "NOT_FOUND", "资产不存在或已失效。")
        if resource["owner_id"] != data.expected_owner or resource["revision"] != data.expected_revision or resource["owner_id"] == data.recipient_id:
            raise ApiError(409, "OWNERSHIP_CONFLICT", "资产归属已变化或接收者与现归属相同，请刷新。")
        if resource["kind"] == "classroom":
            class_id = connection.execute(text("SELECT class_id FROM classrooms WHERE workspace_id=:space AND id=:id"), {"space": space, "id": object_id}).scalar_one()
            if class_id is not None:
                recipient = StaffIdentity(data.recipient_id, 0, "", "")
                teaching_class(connection, recipient, space, class_id)
        connection.execute(text("UPDATE authorization_objects SET owner_id=:recipient,revision=revision+1 WHERE workspace_id=:space AND id=:id"), {"space": space, "id": object_id, "recipient": data.recipient_id})
        if resource["kind"] == "activity":
            # Library versions retain their historical publisher; mutable resource management follows ownership.
            connection.execute(text("UPDATE library_resources SET publisher_id=:recipient,revision=revision+1 WHERE workspace_id=:space AND id=:id"),
                               {"space": space, "id": object_id, "recipient": data.recipient_id})
        connection.execute(text("UPDATE object_grants SET active=false,capabilities='{}',revision=revision+1 WHERE workspace_id=:space AND object_id=:id"), {"space": space, "id": object_id})
        connection.execute(text("INSERT INTO ownership_transfers(workspace_id,id,object_id,previous_owner,new_owner,actor_id) VALUES(:space,:id,:object,:previous,:new,:actor)"),
                           {"space": space, "id": uuid4(), "object": object_id, "previous": resource["owner_id"], "new": data.recipient_id, "actor": identity.account_id})
        _event(connection, space, identity.account_id, "object.transferred", object_id)
