import asyncio
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from openform.config import Settings
from openform.database import DatabaseNotReady, build_engine, probe_database
from openform.errors import ApiError
from openform.runtime.storage import read_document


def create_runtime(settings: Settings, *, engine: Engine | None = None) -> FastAPI:
    if settings.app_origin == settings.runtime_origin or (settings.environment != "development"
            and urlsplit(settings.app_origin).hostname == urlsplit(settings.runtime_origin).hostname):
        raise ValueError("互动页面必须使用独立域名。")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine if engine is not None else build_engine(settings)
        try:
            yield
        finally:
            if engine is None:
                await asyncio.to_thread(app.state.engine.dispose)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    host = urlsplit(settings.runtime_origin).netloc.lower()

    @app.middleware("http")
    async def isolate(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Do not log URLs or CSP reports: both can contain activity-entered content.
        if request.headers.get("host", "").lower() != host or request.url.query or request.method not in {"GET", "HEAD"}:
            response = PlainTextResponse("入口不可用。", status_code=404)
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = PlainTextResponse("页面暂时不可用，请从课堂入口重新打开。", status_code=503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        if "Content-Security-Policy" not in response.headers:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; sandbox"
        return response

    @app.get("/api/health/ready", include_in_schema=False)
    def ready() -> Response:
        try:
            probe_database(app.state.engine)
        except (SQLAlchemyError, DatabaseNotReady):
            return PlainTextResponse("未就绪。", status_code=503)
        return PlainTextResponse("ready")

    @app.api_route("/p/{token}", methods=["GET", "HEAD"], include_in_schema=False)
    def page(request: Request, token: str) -> Response:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return PlainTextResponse("入口不可用。", status_code=404)
        try:
            document, policy = read_document(app.state.engine, token)
        except ApiError as error:
            return PlainTextResponse(error.message, status_code=error.status)
        return HTMLResponse("" if request.method == "HEAD" else document, headers={"Content-Security-Policy": policy})

    return app


def runtime_factory() -> FastAPI:
    return create_runtime(Settings())
