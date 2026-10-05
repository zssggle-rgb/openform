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

from openform.assets.routes import router as assets_router
from openform.authoring.routes import router as authoring_router
from openform.classrooms.routes import router as classroom_router
from openform.config import Settings
from openform.database import DatabaseNotReady, build_engine, probe_database
from openform.errors import ApiError, api_error_handler, error_body
from openform.identity.roster_routes import router as roster_router
from openform.identity.routes import router as identity_router
from openform.library.routes import router as library_router


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
            raw_upload = request.method == "PUT" and "/uploads/" in request.url.path
            if request.method in {"POST", "PUT", "PATCH"} and request.url.path.startswith("/api/") and not raw_upload:
                limit = 65536 if request.url.path.endswith("/bridge") else 16384
                if "/workspaces/" in request.url.path and "/activities" in request.url.path:
                    limit = 13 * 1024 * 1024
                elif "/authoring/imports" in request.url.path:
                    limit = 13 * 1024 * 1024
                elif "/authoring/jobs" in request.url.path:
                    limit = 65536
                elif request.url.path.endswith("/classrooms"):
                    limit = 256 * 1024
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > limit:
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
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
            f"frame-src {settings.runtime_origin}/p/"
        )
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
    app.include_router(roster_router)
    app.include_router(classroom_router)
    app.include_router(assets_router)
    app.include_router(authoring_router)
    app.include_router(library_router)
    if settings.web_directory is not None:
        app.mount("/", StaticFiles(directory=settings.web_directory, html=True), name="web")
    return app


def app_factory() -> FastAPI:
    return create_app(Settings())
