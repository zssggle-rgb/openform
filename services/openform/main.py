import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from openform.config import Settings
from openform.database import DatabaseNotReady, build_engine, probe_database
from openform.errors import ApiError, api_error_handler, error_body
from openform.identity.routes import router as identity_router


def create_app(settings: Settings, *, engine: Engine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine if engine is not None else build_engine(settings)
        try:
            yield
        finally:
            if engine is None:
                await asyncio.to_thread(app.state.engine.dispose)

    app = FastAPI(title="OpenForm", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = uuid4().hex
        try:
            if request.method in {"POST", "PUT", "PATCH"} and request.url.path.startswith(("/api/auth/", "/api/invites/", "/api/workspaces/")):
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 16384:
                        raise ApiError(413, "PAYLOAD_TOO_LARGE", "请求内容超过当前操作的上限。")
                request._body = bytes(body)
            response = await call_next(request)
        except ApiError as error:
            response = await api_error_handler(request, error)
        except Exception as error:
            logging.getLogger("openform").error("request_failed id=%s category=%s", request.state.request_id, type(error).__name__)
            response = JSONResponse(error_body(request, "SERVICE_UNAVAILABLE", "请求失败，请稍后重试。"), status_code=500)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ApiError)
    async def domain_error(request: Request, error: ApiError) -> JSONResponse:
        return await api_error_handler(request, error)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(error_body(request, "INVALID_INPUT", "请求字段不符合要求。"), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code = "NOT_FOUND" if error.status_code == 404 else "INVALID_INPUT"
        return JSONResponse(error_body(request, code, "请求的入口不可用。"), status_code=error.status_code)

    @app.get("/api/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive", "service": "openform-api"}

    @app.get("/api/health/ready")
    def ready() -> dict[str, str]:
        try:
            probe_database(app.state.engine)
        except (SQLAlchemyError, DatabaseNotReady):
            raise ApiError(503, "SERVICE_UNAVAILABLE", "服务暂未就绪，请稍后重试。", retryable=True) from None
        return {"status": "ready", "service": "openform-api"}

    app.include_router(identity_router)
    if settings.web_directory is not None:
        app.mount("/", StaticFiles(directory=settings.web_directory, html=True), name="web")
    return app


def app_factory() -> FastAPI:
    return create_app(Settings())
