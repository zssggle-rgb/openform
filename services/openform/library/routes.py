from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request

from openform.identity.routes import Identity
from openform.library import service
from openform.library.schemas import CopyInput, PublicationInput, WithdrawalInput

router = APIRouter(prefix="/api/workspaces/{workspace_id}")


@router.get("/library")
def catalog(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None,
            q: str = Query(default="", max_length=80), subject: str = Query(default="", max_length=40),
            grade: str = Query(default="", max_length=40)) -> dict[str, Any]:
    return service.list_resources(request.app.state.engine, identity, workspace_id, cursor, q, subject, grade)


@router.get("/library/{resource_id}")
def detail(workspace_id: UUID, resource_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return service.resource_detail(request.app.state.engine, identity, workspace_id, resource_id)


@router.post("/library/{resource_id}/copies", status_code=201)
def copy(workspace_id: UUID, resource_id: UUID, data: CopyInput, request: Request, identity: Identity) -> dict[str, Any]:
    return service.copy_resource(request.app.state.engine, request.app.state.settings, identity, workspace_id, resource_id, data)


@router.post("/library/{resource_id}/preview")
def preview(workspace_id: UUID, resource_id: UUID, data: CopyInput, request: Request, identity: Identity) -> dict[str, Any]:
    return service.preview(request.app.state.engine, request.app.state.settings, identity, workspace_id, resource_id, data.number)


@router.post("/library/{resource_id}/withdraw", status_code=204)
def withdraw(workspace_id: UUID, resource_id: UUID, data: WithdrawalInput, request: Request, identity: Identity) -> None:
    service.withdraw(request.app.state.engine, identity, workspace_id, resource_id, data.expected_revision)


@router.get("/activities/{activity_id}/resource")
def publication(workspace_id: UUID, activity_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return service.publication_state(request.app.state.engine, identity, workspace_id, activity_id)


@router.post("/activities/{activity_id}/resource")
def publish(workspace_id: UUID, activity_id: UUID, data: PublicationInput, request: Request, identity: Identity) -> dict[str, Any]:
    return service.publish_resource(request.app.state.engine, identity, workspace_id, activity_id, data)
