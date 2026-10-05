import hmac
import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from openform.errors import ApiError
from openform.identity import authorization, roster, students
from openform.identity.accounts import consume_rate
from openform.identity.roster_schemas import (
    AssignmentInput,
    ClassChangeInput,
    ClassInput,
    CredentialInput,
    StudentChangeInput,
    StudentCodeInput,
    StudentInput,
)
from openform.identity.routes import Identity, require_origin
from openform.identity.security import csrf_token

router = APIRouter(prefix="/api")


@router.get("/workspaces/{workspace_id}/objects/{object_id}/grants")
def grants(workspace_id: UUID, object_id: UUID, request: Request, identity: Identity,
           cursor: UUID | None = None) -> dict[str, Any]:
    return authorization.list_grants(request.app.state.engine, identity, workspace_id, object_id, cursor)


@router.get("/workspaces/{workspace_id}/objects/{object_id}/collaborators")
def collaborators(workspace_id: UUID, object_id: UUID, request: Request, identity: Identity,
                  cursor: UUID | None = None) -> dict[str, Any]:
    return authorization.list_collaborators(request.app.state.engine, identity, workspace_id, object_id, cursor)


@router.patch("/workspaces/{workspace_id}/objects/{object_id}/grants/{account_id}", status_code=204)
def grant_change(workspace_id: UUID, object_id: UUID, account_id: UUID, data: authorization.GrantInput,
                 request: Request, identity: Identity) -> None:
    authorization.change_grant(request.app.state.engine, identity, workspace_id, object_id, account_id, data)


@router.get("/workspaces/{workspace_id}/classes")
def classes(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return roster.list_classes(request.app.state.engine, identity, workspace_id, cursor)


@router.post("/workspaces/{workspace_id}/classes", status_code=201)
def class_create(workspace_id: UUID, data: ClassInput, request: Request, identity: Identity) -> dict[str, UUID]:
    return {"id": roster.create_class(request.app.state.engine, identity, workspace_id, data)}


@router.patch("/workspaces/{workspace_id}/classes/{class_id}", status_code=204)
def class_change(workspace_id: UUID, class_id: UUID, data: ClassChangeInput, request: Request, identity: Identity) -> None:
    roster.change_class(request.app.state.engine, identity, workspace_id, class_id, data)


@router.get("/workspaces/{workspace_id}/classes/{class_id}/assignments")
def assignments(workspace_id: UUID, class_id: UUID, request: Request, identity: Identity,
                cursor: UUID | None = None, account_id: UUID | None = None) -> dict[str, Any]:
    return roster.list_assignments(request.app.state.engine, identity, workspace_id, class_id, cursor, account_id)


@router.patch("/workspaces/{workspace_id}/classes/{class_id}/assignments/{account_id}", status_code=204)
def assignment_change(workspace_id: UUID, class_id: UUID, account_id: UUID, data: AssignmentInput,
                      request: Request, identity: Identity) -> None:
    roster.change_assignment(request.app.state.engine, identity, workspace_id, class_id, account_id, data)


@router.get("/workspaces/{workspace_id}/students")
def student_list(workspace_id: UUID, request: Request, identity: Identity, class_id: UUID | None = None,
                 cursor: UUID | None = None, q: str = Query(default="", max_length=80)) -> dict[str, Any]:
    return roster.list_students(request.app.state.engine, identity, workspace_id, class_id=class_id, cursor=cursor, query=q)


@router.post("/workspaces/{workspace_id}/students", status_code=201)
def student_create(workspace_id: UUID, data: StudentInput, request: Request, identity: Identity) -> dict[str, UUID]:
    return {"id": roster.create_student(request.app.state.engine, identity, workspace_id, data)}


@router.patch("/workspaces/{workspace_id}/students/{student_id}", status_code=204)
def student_change(workspace_id: UUID, student_id: UUID, data: StudentChangeInput, request: Request, identity: Identity) -> None:
    roster.change_student(request.app.state.engine, identity, workspace_id, student_id, data)


@router.post("/workspaces/{workspace_id}/students/{student_id}/code")
def code_issue(workspace_id: UUID, student_id: UUID, data: CredentialInput, request: Request, identity: Identity) -> dict[str, Any]:
    return students.issue_code(request.app.state.engine, identity, workspace_id, student_id, data.expected_epoch)


@router.delete("/workspaces/{workspace_id}/students/{student_id}/code", status_code=204)
def code_revoke(workspace_id: UUID, student_id: UUID, expected_epoch: int, request: Request, identity: Identity) -> None:
    if expected_epoch < 1:
        raise ApiError(422, "INVALID_INPUT", "需要当前个人码代次。")
    students.revoke_code(request.app.state.engine, identity, workspace_id, student_id, expected_epoch)


def current_student(request: Request) -> students.StudentIdentity:
    token = request.cookies.get(students.STUDENT_COOKIE)
    if token is None:
        raise ApiError(401, "UNAUTHENTICATED", "请验证个人进入码。")
    identity = students.identify_student(request.app.state.engine, token)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not re.fullmatch(r"[a-f0-9]{64}", supplied) or not hmac.compare_digest(supplied, csrf_token(token)):
            raise ApiError(403, "FORBIDDEN", "页面验证已失效，请刷新重试。")
    return identity


Student = Annotated[students.StudentIdentity, Depends(current_student)]


@router.post("/student-auth/code", dependencies=[Depends(require_origin)])
def code_exchange(data: StudentCodeInput, request: Request, response: Response) -> dict[str, str]:
    consume_rate(request.app.state.engine, f"student-ip:{request.client.host if request.client else 'unknown'}", limit=1000)
    token = students.exchange_code(request.app.state.engine, data.code)
    response.set_cookie(students.STUDENT_COOKIE, token, max_age=43200, httponly=True, samesite="lax", path="/",
                        secure=request.app.state.settings.environment != "development")
    return {"status": "authenticated"}


@router.get("/student-auth/session")
def student_session(request: Request, identity: Student) -> dict[str, Any]:
    return {**students.student_session(request.app.state.engine, identity),
            "csrf_token": csrf_token(request.cookies[students.STUDENT_COOKIE])}


@router.post("/student-auth/logout", status_code=204)
def student_logout(request: Request, response: Response, identity: Student) -> None:
    students.logout_student(request.app.state.engine, identity)
    response.delete_cookie(students.STUDENT_COOKIE, path="/", httponly=True, samesite="lax",
                           secure=request.app.state.settings.environment != "development")
