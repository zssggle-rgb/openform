from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from openform.authoring import imports
from openform.authoring.imports import ImportInput
from openform.authoring.source import draft_source
from openform.identity.context import workspace_transaction
from openform.identity.routes import Identity
from openform.jobs import service
from openform.jobs.service import GenerateInput
from openform.models.ark import available

router = APIRouter(prefix="/api/workspaces/{workspace_id}")


@router.get("/authoring/config")
def authoring_config(workspace_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    with workspace_transaction(request.app.state.engine, identity, workspace_id) as (connection, workspace):
        return {"model_available": available(request.app.state.settings) and workspace["is_teacher"],
                "model": request.app.state.settings.model_id, "token_quota": request.app.state.settings.workspace_model_token_quota}


@router.get("/activities/{activity_id}/source")
def source_get(workspace_id: UUID, activity_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    with workspace_transaction(request.app.state.engine, identity, workspace_id) as (connection, workspace):
        return draft_source(connection, identity, workspace, activity_id)


@router.post("/authoring/jobs", status_code=202)
def generation_start(workspace_id: UUID, data: GenerateInput, request: Request, identity: Identity) -> dict[str, Any]:
    return service.enqueue(request.app.state.engine, request.app.state.settings, identity, workspace_id, data)


@router.get("/authoring/jobs")
def job_list(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return service.list_jobs(request.app.state.engine, identity, workspace_id, cursor)


@router.get("/authoring/jobs/{job_id}")
def job_get(workspace_id: UUID, job_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return service.job_detail(request.app.state.engine, identity, workspace_id, job_id)


@router.post("/authoring/imports")
def import_start(workspace_id: UUID, data: ImportInput, request: Request, identity: Identity) -> dict[str, Any]:
    return imports.import_page(request.app.state.engine, request.app.state.settings, identity, workspace_id, data)


@router.get("/authoring/imports/{import_id}")
def import_get(workspace_id: UUID, import_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return imports.import_detail(request.app.state.engine, identity, workspace_id, import_id)
