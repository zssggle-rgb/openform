from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from openform.identity.routes import Identity
from openform.school.lifecycle import DeleteInput, delete_records
from openform.school.ownership import TransferInput, list_assets, transfer_asset
from openform.school.policies import PolicyInput, change_policy, list_events, policy_detail, workspace_status

router = APIRouter(prefix="/api/workspaces/{workspace_id}")


@router.get("/policy")
def policy(workspace_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return policy_detail(request.app.state.engine, request.app.state.settings, identity, workspace_id)


@router.patch("/policy")
def policy_change(workspace_id: UUID, data: PolicyInput, request: Request, identity: Identity) -> dict[str, Any]:
    return change_policy(request.app.state.engine, request.app.state.settings, identity, workspace_id, data)


@router.get("/status")
def status(workspace_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return workspace_status(request.app.state.engine, request.app.state.settings, identity, workspace_id)


@router.get("/assets")
def assets(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return list_assets(request.app.state.engine, identity, workspace_id, cursor)


@router.get("/audit")
def audit(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return list_events(request.app.state.engine, identity, workspace_id, cursor)


@router.post("/assets/{object_id}/transfer", status_code=204)
def transfer(workspace_id: UUID, object_id: UUID, data: TransferInput, request: Request, identity: Identity) -> None:
    transfer_asset(request.app.state.engine, identity, workspace_id, object_id, data)


@router.delete("/classrooms/{classroom_id}/records")
def records_delete(workspace_id: UUID, classroom_id: UUID, data: DeleteInput, request: Request, identity: Identity) -> dict[str, Any]:
    return delete_records(request.app.state.engine, identity, workspace_id, classroom_id, data)
