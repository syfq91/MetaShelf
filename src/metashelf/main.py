"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from metashelf import __version__
from metashelf.config import Settings, get_settings


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
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title="MetaShelf",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings

    @app.get("/healthz", tags=["system"])
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app


app = create_app()
