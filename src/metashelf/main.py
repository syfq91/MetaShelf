"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

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
from metashelf.web.routers import auth, pages


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
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    try:
        yield
    finally:
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

    return app


app = create_app()
