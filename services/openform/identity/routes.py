import hmac
import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from openform.errors import ApiError
from openform.identity import accounts, members
from openform.identity.context import StaffIdentity
from openform.identity.schemas import InviteAcceptInput, InviteInput, LoginInput, MemberInput, RegistrationInput
from openform.identity.security import COOKIE_NAME, csrf_token

router = APIRouter(prefix="/api")


def require_origin(request: Request) -> None:
    if request.headers.get("origin") != request.app.state.settings.app_origin:
        raise ApiError(403, "FORBIDDEN", "请求来源无法验证，请从应用页面重试。")


def current_identity(request: Request) -> StaffIdentity:
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        raise ApiError(401, "UNAUTHENTICATED", "请先登录。")
    identity = accounts.identify(request.app.state.engine, token)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not re.fullmatch(r"[a-f0-9]{64}", supplied) or not hmac.compare_digest(supplied, csrf_token(token)):
            raise ApiError(403, "FORBIDDEN", "页面验证已失效，请刷新后重试。")
    return identity


Identity = Annotated[StaffIdentity, Depends(current_identity)]


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=43200, httponly=True,
                        secure=request.app.state.settings.environment != "development", samesite="lax", path="/")


@router.post("/auth/register", dependencies=[Depends(require_origin)], status_code=201)
def register(data: RegistrationInput, request: Request, response: Response) -> dict[str, Any]:
    accounts.consume_rate(request.app.state.engine, f"register:{request.client.host if request.client else 'unknown'}",
                          limit=10, seconds=300)
    account_id, token = accounts.register(request.app.state.engine, data)
    set_session_cookie(request, response, token)
    return {"account_id": account_id}


@router.post("/auth/login", dependencies=[Depends(require_origin)])
def login(data: LoginInput, request: Request, response: Response) -> dict[str, str]:
    accounts.consume_rate(request.app.state.engine, f"login-ip:{request.client.host if request.client else 'unknown'}",
                          limit=60, seconds=300)
    token = accounts.login(request.app.state.engine, data)
    set_session_cookie(request, response, token)
    return {"status": "authenticated"}


@router.get("/auth/session")
def session(request: Request, identity: Identity) -> dict[str, Any]:
    return {"account_id": identity.account_id, "display_name": identity.display_name,
            "csrf_token": csrf_token(request.cookies[COOKIE_NAME]),
            "workspaces": accounts.list_workspaces(request.app.state.engine, identity)}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, identity: Identity) -> None:
    accounts.logout(request.app.state.engine, identity)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True,
                           secure=request.app.state.settings.environment != "development", samesite="lax")


@router.get("/workspaces/{workspace_id}/members")
def member_list(workspace_id: UUID, request: Request, identity: Identity,
                cursor: UUID | None = None, q: str = Query(default="", max_length=80)) -> dict[str, Any]:
    return members.list_members(request.app.state.engine, identity, workspace_id, cursor, q)


@router.patch("/workspaces/{workspace_id}/members/{account_id}", status_code=204)
def member_change(workspace_id: UUID, account_id: UUID, data: MemberInput,
                  request: Request, identity: Identity) -> None:
    members.change_member(request.app.state.engine, identity, workspace_id, account_id, data)


@router.post("/workspaces/{workspace_id}/invites", status_code=201)
def invite_create(workspace_id: UUID, data: InviteInput, request: Request, identity: Identity) -> dict[str, Any]:
    return members.create_invite(request.app.state.engine, identity, workspace_id, data)


@router.get("/workspaces/{workspace_id}/invites")
def invite_list(workspace_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return {"items": members.list_invites(request.app.state.engine, identity, workspace_id)}


@router.delete("/workspaces/{workspace_id}/invites/{invite_id}", status_code=204)
def invite_revoke(workspace_id: UUID, invite_id: UUID, request: Request, identity: Identity) -> None:
    members.revoke_invite(request.app.state.engine, identity, workspace_id, invite_id)


@router.post("/invites/accept")
def invite_accept(data: InviteAcceptInput, request: Request, identity: Identity) -> dict[str, Any]:
    return {"workspace_id": members.accept_invite(request.app.state.engine, identity, data.token)}


@router.post("/invites/preview")
def invite_preview(data: InviteAcceptInput, request: Request, identity: Identity) -> dict[str, Any]:
    return members.preview_invite(request.app.state.engine, identity, data.token)
