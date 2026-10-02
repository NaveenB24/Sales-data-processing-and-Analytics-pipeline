"""Application factory: middleware, routers, lifespan and static hosting."""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.db import init_db
from app.logging_config import configure_logging, get_logger, set_correlation_id
from app.processing.events import hub
from app.processing.queue import job_queue
from app.routers import admin, auth, jobs, reports, ws

log = get_logger("http")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    hub.bind_loop(asyncio.get_running_loop())
    job_queue.start()
    log.info(
        "app.started",
        version=settings.version,
        environment=settings.environment,
        worker_pool_size=settings.worker_pool_size,
    )
    try:
        yield
    finally:
        job_queue.stop()
        log.info("app.stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID", "Content-Disposition"],
    )

    @app.middleware("http")
    async def correlation_and_access_log(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        set_correlation_id(correlation_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.error(
                "http.unhandled",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                exc_info=True,
            )
            raise
        finally:
            set_correlation_id(None)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Correlation-ID"] = correlation_id
        if request.url.path.startswith("/api"):
            level = log.warning if response.status_code >= 400 else log.info
            level(
                "http.request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(p) for p in first.get("loc", ())[1:]) or "request"
        return JSONResponse(
            status_code=422,
            content={"detail": f"{location}: {first.get('msg', 'invalid request')}"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_request: Request, _exc: Exception):
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    for module in (auth, jobs, reports, admin, ws):
        app.include_router(module.router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA when `frontend/dist` exists (single-origin production mode)."""
    if not FRONTEND_DIST.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


app = create_app()
