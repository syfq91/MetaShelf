"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from metashelf import __version__
from metashelf.auth.deps import AuthRedirectError
from metashelf.auth.security import LoginRateLimiter
from metashelf.config import Settings, get_settings
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.jobs.handlers import (
    handle_auto_match,
    handle_fetch_show_episodes,
    handle_scan_library,
)
from metashelf.jobs.queue import JobWorker
from metashelf.web.routers import auth, jobs, movies, pages, tv
from metashelf.web.routers import settings as settings_router


class HealthResponse(BaseModel):
    """Health check response payload."""

    status: str
    version: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown."""
    settings: Settings = app.state.settings
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    settings.thumbnails_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.resolved_database_url)
    engine = create_async_engine_with_wal(settings.resolved_database_url)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory
    http_client = httpx.AsyncClient()
    app.state.http_client = http_client

    worker = JobWorker(
        session_factory=session_factory,
        http_client=http_client,
        settings=settings,
        handlers={
            "scan_library": handle_scan_library,
            "auto_match": handle_auto_match,
            "fetch_show_episodes": handle_fetch_show_episodes,
        },
    )
    app.state.job_worker = worker
    await worker.start()
    try:
        yield
    finally:
        await worker.stop()
        await http_client.aclose()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title="MetaShelf",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.login_limiter = LoginRateLimiter()

    @app.exception_handler(AuthRedirectError)
    async def auth_redirect_handler(_request: Request, exc: AuthRedirectError) -> RedirectResponse:
        return RedirectResponse(exc.location, status_code=status.HTTP_303_SEE_OTHER)

    static_dir = Path(__file__).resolve().parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/healthz", tags=["system"])
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(movies.router)
    app.include_router(tv.router)
    app.include_router(jobs.router)
    app.include_router(settings_router.router)

    return app


app = create_app()
