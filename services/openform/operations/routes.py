import hashlib
import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import text

from openform.errors import ApiError
from openform.identity.accounts import consume_rate
from openform.identity.routes import require_origin
from openform.identity.security import csrf_token, new_token, token_digest

router = APIRouter(prefix="/api/ops")
COOKIE = "openform_operator"


class OperatorLogin(BaseModel):
    credential: SecretStr = Field(min_length=43, max_length=43)


def credential(request: Request) -> str:
    path = request.app.state.settings.operator_key_file
    try:
        value = path.read_text().strip() if path else ""
        token_digest(value)
        return value
    except (OSError, ApiError):
        raise ApiError(503, "OPERATOR_UNAVAILABLE", "独立运维凭据尚未配置，请联系部署负责人。") from None


def operator(request: Request) -> str:
    value = request.cookies.get(COOKIE, "")
    digest = token_digest(value)
    key_digest = hashlib.sha256(credential(request).encode()).hexdigest()
    with request.app.state.engine.connect() as connection:
        valid = connection.execute(text("SELECT 1 FROM operator_sessions WHERE token_digest=:digest "
                                        "AND credential_digest=:key AND NOT revoked AND expires_at>now()"),
                                   {"digest": digest, "key": key_digest}).scalar_one_or_none()
    if valid is None:
        raise ApiError(401, "UNAUTHENTICATED", "请使用独立运维凭据登录。")
    if request.method not in {"GET", "HEAD"}:
        require_origin(request)
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(value)):
            raise ApiError(403, "FORBIDDEN", "运维页面验证已失效，请刷新。")
    return value


Operator = Annotated[str, Depends(operator)]


@router.post("/login", dependencies=[Depends(require_origin)])
def login(data: OperatorLogin, request: Request, response: Response) -> dict[str, str]:
    consume_rate(request.app.state.engine, "operator-login", limit=15, seconds=300)
    if not hmac.compare_digest(data.credential.get_secret_value().encode(), credential(request).encode()):
        raise ApiError(401, "UNAUTHENTICATED", "独立运维凭据不正确。")
    token = new_token()
    with request.app.state.engine.begin() as connection:
        connection.execute(text("DELETE FROM operator_sessions WHERE expires_at<now() OR revoked"))
        connection.execute(text("INSERT INTO operator_sessions (token_digest,credential_digest,expires_at) "
                                "VALUES (:digest,:key,now()+interval '12 hours')"),
                           {"digest": token_digest(token), "key": hashlib.sha256(credential(request).encode()).hexdigest()})
    response.set_cookie(COOKIE, token, max_age=43200, httponly=True, samesite="lax", path="/api/ops",
                        secure=request.app.state.settings.environment != "development")
    return {"status": "authenticated"}


@router.get("/status")
def status(request: Request, token: Operator) -> dict[str, Any]:
    with request.app.state.engine.connect() as connection:
        value: dict[str, Any] = connection.execute(text("SELECT operator_status()")).scalar_one()
    return {**value, "csrf_token": csrf_token(token), "model_configured": bool(
        request.app.state.settings.model_api_key_file
        and request.app.state.settings.model_api_key_file.is_file()
        and request.app.state.settings.model_api_key_file.read_text().strip()),
        "model_id": request.app.state.settings.model_id}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, token: Operator) -> None:
    with request.app.state.engine.begin() as connection:
        connection.execute(text("UPDATE operator_sessions SET revoked=true WHERE token_digest=:digest"),
                           {"digest": token_digest(token)})
    response.delete_cookie(COOKIE, path="/api/ops", httponly=True, samesite="lax",
                           secure=request.app.state.settings.environment != "development")
