from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import text

from openform.analysis import service
from openform.analysis.schemas import AnalysisInput, ReviewInput, ShareInput
from openform.analysis.sharing import shared_content
from openform.classrooms.participants import Participant, actor, participant_transaction
from openform.classrooms.routes import Guest
from openform.classrooms.service import eligible, require_classroom
from openform.identity.roster_routes import Student
from openform.identity.routes import Identity
from openform.jobs.service import job_detail

router = APIRouter()


@router.post("/api/workspaces/{workspace_id}/classrooms/{classroom_id}/analysis", status_code=202)
def create(workspace_id: UUID, classroom_id: UUID, data: AnalysisInput, request: Request, identity: Identity) -> dict[str, Any]:
    return service.enqueue_analysis(request.app.state.engine, request.app.state.settings, identity, workspace_id, classroom_id, data)


@router.get("/api/workspaces/{workspace_id}/analysis/jobs/{job_id}")
def job(workspace_id: UUID, job_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return job_detail(request.app.state.engine, identity, workspace_id, job_id)


@router.get("/api/workspaces/{workspace_id}/classrooms/{classroom_id}/analysis/jobs")
def tasks(workspace_id: UUID, classroom_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return service.list_tasks(request.app.state.engine, identity, workspace_id, classroom_id, cursor)


@router.get("/api/workspaces/{workspace_id}/classrooms/{classroom_id}/reports")
def reports(workspace_id: UUID, classroom_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return service.list_reports(request.app.state.engine, identity, workspace_id, classroom_id, cursor)


@router.get("/api/workspaces/{workspace_id}/reports/{report_id}")
def detail(workspace_id: UUID, report_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return service.report_detail(request.app.state.engine, identity, workspace_id, report_id)


@router.post("/api/workspaces/{workspace_id}/reports/{report_id}/review", status_code=204)
def review(workspace_id: UUID, report_id: UUID, data: ReviewInput, request: Request, identity: Identity) -> None:
    service.review_report(request.app.state.engine, identity, workspace_id, report_id, data)


@router.post("/api/workspaces/{workspace_id}/reports/{report_id}/share", status_code=204)
def share(workspace_id: UUID, report_id: UUID, data: ShareInput, request: Request, identity: Identity) -> None:
    service.share_report(request.app.state.engine, identity, workspace_id, report_id, data)


def shared_summary(request: Request, identity: Participant, classroom_id: UUID) -> dict[str, Any]:
    with participant_transaction(request.app.state.engine, identity) as (connection, workspace):
        classroom = require_classroom(connection, workspace["id"], classroom_id)
        kind, actor_id = actor(identity)
        eligible(connection, workspace["id"], classroom, kind, actor_id)
        participated = connection.execute(text("SELECT 1 FROM activity_attempts WHERE workspace_id=:space AND classroom_id=:id "
                                               "AND actor_kind=:kind AND actor_id=:actor LIMIT 1"),
                                          {"space": workspace["id"], "id": classroom_id, "kind": kind, "actor": actor_id}).scalar_one_or_none()
        if participated is None:
            return {"items": []}
        return shared_content(connection, workspace["id"], classroom)


@router.get("/api/student/classrooms/{classroom_id}/shared-summary")
def student_shared(classroom_id: UUID, request: Request, identity: Student) -> dict[str, Any]:
    return shared_summary(request, identity, classroom_id)


@router.get("/api/guest/classrooms/{classroom_id}/shared-summary")
def guest_shared(classroom_id: UUID, request: Request, identity: Guest) -> dict[str, Any]:
    return shared_summary(request, identity, classroom_id)


@router.get("/api/workspaces/{workspace_id}/reports/{report_id}/evidence/{record_id}")
def evidence(workspace_id: UUID, report_id: UUID, record_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return service.evidence_record(request.app.state.engine, identity, workspace_id, report_id, record_id)
