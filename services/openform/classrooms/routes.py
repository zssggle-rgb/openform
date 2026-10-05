import hmac
import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from openform.activities import samples
from openform.activities import service as activities
from openform.activities.schemas import DraftInput, PublishInput, SampleInput, TrialInput
from openform.classrooms import guests, participants, records, service, summary
from openform.classrooms.schemas import AttemptInput, ClassroomInput, GuestInput, JoinInput, StateInput
from openform.errors import ApiError
from openform.identity.accounts import consume_rate
from openform.identity.roster_routes import Student
from openform.identity.routes import Identity, require_origin
from openform.identity.security import csrf_token

router = APIRouter(prefix="/api")


@router.get("/workspaces/{workspace_id}/activities")
def activity_list(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return activities.list_activities(request.app.state.engine, identity, workspace_id, cursor)


@router.post("/workspaces/{workspace_id}/activities", status_code=201)
def activity_create(workspace_id: UUID, data: DraftInput, request: Request, identity: Identity) -> dict[str, Any]:
    return activities.save_draft(request.app.state.engine, request.app.state.settings, identity, workspace_id, data)


@router.post("/workspaces/{workspace_id}/activities/samples", status_code=201)
def sample_create(workspace_id: UUID, data: SampleInput, request: Request, identity: Identity) -> dict[str, Any]:
    return activities.save_draft(request.app.state.engine, request.app.state.settings, identity, workspace_id, samples.sample_draft(data.kind))


@router.get("/workspaces/{workspace_id}/activities/{activity_id}")
def activity_get(workspace_id: UUID, activity_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return activities.activity_detail(request.app.state.engine, identity, workspace_id, activity_id)


@router.patch("/workspaces/{workspace_id}/activities/{activity_id}")
def activity_save(workspace_id: UUID, activity_id: UUID, data: DraftInput, request: Request, identity: Identity) -> dict[str, Any]:
    return activities.save_draft(request.app.state.engine, request.app.state.settings, identity, workspace_id, data, activity_id)


@router.post("/workspaces/{workspace_id}/activities/{activity_id}/trials", status_code=201)
def trial_start(workspace_id: UUID, activity_id: UUID, data: TrialInput, request: Request, identity: Identity) -> dict[str, Any]:
    return activities.start_trial(request.app.state.engine, request.app.state.settings, identity, workspace_id, activity_id, data.expected_revision)


@router.post("/workspaces/{workspace_id}/activities/{activity_id}/publish")
def activity_publish(workspace_id: UUID, activity_id: UUID, data: PublishInput, request: Request, identity: Identity) -> dict[str, Any]:
    return activities.publish(request.app.state.engine, identity, workspace_id, activity_id, data)


@router.get("/workspaces/{workspace_id}/classrooms")
def classroom_list(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return service.list_classrooms(request.app.state.engine, identity, workspace_id, cursor)


@router.post("/workspaces/{workspace_id}/classrooms", status_code=201)
def classroom_create(workspace_id: UUID, data: ClassroomInput, request: Request, identity: Identity) -> dict[str, Any]:
    return service.create_classroom(request.app.state.engine, identity, workspace_id, data)


@router.get("/workspaces/{workspace_id}/classrooms/{classroom_id}")
def classroom_get(workspace_id: UUID, classroom_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return service.classroom_detail(request.app.state.engine, identity, workspace_id, classroom_id)


@router.patch("/workspaces/{workspace_id}/classrooms/{classroom_id}/state", status_code=204)
def classroom_state(workspace_id: UUID, classroom_id: UUID, data: StateInput, request: Request, identity: Identity) -> None:
    service.change_state(request.app.state.engine, identity, workspace_id, classroom_id, data)


@router.get("/workspaces/{workspace_id}/classrooms/{classroom_id}/summary")
def classroom_summary(workspace_id: UUID, classroom_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return summary.classroom_summary(request.app.state.engine, identity, workspace_id, classroom_id)


@router.get("/workspaces/{workspace_id}/classrooms/{classroom_id}/records")
def classroom_records(workspace_id: UUID, classroom_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return summary.classroom_records(request.app.state.engine, identity, workspace_id, classroom_id, cursor)


@router.post("/workspaces/{workspace_id}/attempts/{attempt_id}/bridge")
def trial_bridge(workspace_id: UUID, attempt_id: UUID, data: dict[str, Any], request: Request, identity: Identity) -> Any:
    return records.execute_bridge(request.app.state.engine, identity, attempt_id, data, workspace_id=workspace_id)


@router.get("/workspaces/{workspace_id}/attempts/{attempt_id}/operations")
def trial_operation(workspace_id: UUID, attempt_id: UUID, request: Request, identity: Identity,
                    method: str, key: str = Query(max_length=128)) -> dict[str, Any]:
    return records.find_operation(request.app.state.engine, identity, attempt_id, method, key, workspace_id=workspace_id)


def current_guest(request: Request) -> guests.GuestIdentity:
    token = request.cookies.get(guests.GUEST_COOKIE)
    if token is None:
        raise ApiError(401, "UNAUTHENTICATED", "请重新进入快速课堂。")
    identity = guests.identify_guest(request.app.state.engine, token)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not re.fullmatch(r"[a-f0-9]{64}", supplied) or not hmac.compare_digest(supplied, csrf_token(token)):
            raise ApiError(403, "FORBIDDEN", "页面验证已失效，请刷新重试。")
    return identity


Guest = Annotated[guests.GuestIdentity, Depends(current_guest)]


@router.post("/guest-auth/enter", dependencies=[Depends(require_origin)])
def guest_enter(data: GuestInput, request: Request, response: Response) -> dict[str, str]:
    consume_rate(request.app.state.engine, f"guest-ip:{request.client.host if request.client else 'unknown'}", limit=300)
    token = guests.enter_guest(request.app.state.engine, data.code, data.display_name)
    response.set_cookie(guests.GUEST_COOKIE, token, max_age=43200, httponly=True, samesite="lax", path="/",
                        secure=request.app.state.settings.environment != "development")
    return {"status": "authenticated"}


@router.get("/guest-auth/session")
def guest_get(request: Request, identity: Guest) -> dict[str, Any]:
    return {**guests.guest_session(request.app.state.engine, identity), "csrf_token": csrf_token(request.cookies[guests.GUEST_COOKIE])}


@router.post("/guest-auth/logout", status_code=204)
def guest_logout(request: Request, response: Response, identity: Guest) -> None:
    guests.logout_guest(request.app.state.engine, identity)
    response.delete_cookie(guests.GUEST_COOKIE, path="/", httponly=True, samesite="lax",
                           secure=request.app.state.settings.environment != "development")


@router.post("/student/classrooms/join")
def student_join(data: JoinInput, request: Request, identity: Student) -> dict[str, Any]:
    return participants.join_classroom(request.app.state.engine, request.app.state.settings, identity, code=data.code)


@router.post("/student/classrooms/{classroom_id}/attempts")
def student_retry(classroom_id: UUID, data: AttemptInput, request: Request, identity: Student) -> dict[str, Any]:
    return participants.join_classroom(request.app.state.engine, request.app.state.settings, identity,
                                       classroom_id=classroom_id, previous_attempt_id=data.previous_attempt_id)


@router.post("/student/classrooms/{classroom_id}/join")
def student_reopen(classroom_id: UUID, request: Request, identity: Student) -> dict[str, Any]:
    return participants.join_classroom(request.app.state.engine, request.app.state.settings, identity, classroom_id=classroom_id)


@router.post("/guest/classrooms/{classroom_id}/join")
def guest_join(classroom_id: UUID, request: Request, identity: Guest) -> dict[str, Any]:
    return participants.join_classroom(request.app.state.engine, request.app.state.settings, identity, classroom_id=classroom_id)


@router.post("/guest/classrooms/{classroom_id}/attempts")
def guest_retry(classroom_id: UUID, data: AttemptInput, request: Request, identity: Guest) -> dict[str, Any]:
    return participants.join_classroom(request.app.state.engine, request.app.state.settings, identity,
                                       classroom_id=classroom_id, previous_attempt_id=data.previous_attempt_id)


@router.post("/student/attempts/{attempt_id}/bridge")
def student_bridge(attempt_id: UUID, data: dict[str, Any], request: Request, identity: Student) -> Any:
    return records.execute_bridge(request.app.state.engine, identity, attempt_id, data)


@router.post("/guest/attempts/{attempt_id}/bridge")
def guest_bridge(attempt_id: UUID, data: dict[str, Any], request: Request, identity: Guest) -> Any:
    return records.execute_bridge(request.app.state.engine, identity, attempt_id, data)


@router.get("/student/attempts/{attempt_id}/operations")
def student_operation(attempt_id: UUID, request: Request, identity: Student, method: str, key: str = Query(max_length=128)) -> dict[str, Any]:
    return records.find_operation(request.app.state.engine, identity, attempt_id, method, key)


@router.get("/guest/attempts/{attempt_id}/operations")
def guest_operation(attempt_id: UUID, request: Request, identity: Guest, method: str, key: str = Query(max_length=128)) -> dict[str, Any]:
    return records.find_operation(request.app.state.engine, identity, attempt_id, method, key)


@router.get("/student/history")
def student_history(request: Request, identity: Student, cursor: UUID | None = None) -> dict[str, Any]:
    return participants.own_history(request.app.state.engine, identity, cursor)


@router.get("/guest/history")
def guest_history(request: Request, identity: Guest, cursor: UUID | None = None) -> dict[str, Any]:
    return participants.own_history(request.app.state.engine, identity, cursor)
