"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select

from metashelf import __version__
from metashelf.auth.deps import AuthRedirectError
from metashelf.auth.security import LoginRateLimiter
from metashelf.config import Settings, get_settings
from metashelf.db.models import Item, Job, Library
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.jobs.handlers import (
    handle_auto_match,
    handle_fetch_lyrics,
    handle_fetch_show_episodes,
    handle_fetch_subtitles,
    handle_scan_library,
)
from metashelf.jobs.queue import JobWorker
from metashelf.jobs.scheduler import LibraryScheduler, LibraryWatcher
from metashelf.logging_config import configure_logging
from metashelf.web.routers import auth, comics, ebooks, jobs, movies, music, pages, tv
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
    settings.ensure_secret_key()
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
            "fetch_subtitles": handle_fetch_subtitles,
            "fetch_lyrics": handle_fetch_lyrics,
        },
    )
    app.state.job_worker = worker
    await worker.start()
    scheduler = LibraryScheduler(session_factory=session_factory)
    app.state.scheduler = scheduler
    await scheduler.start()
    watcher: LibraryWatcher | None = None
    if settings.watch_enabled:
        watcher = LibraryWatcher(session_factory=session_factory)
        app.state.watcher = watcher
        await watcher.start()
    try:
        yield
    finally:
        if watcher is not None:
            await watcher.stop()
        await scheduler.stop()
        await worker.stop()
        await http_client.aclose()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level, resolved_settings.log_format)
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

    @app.get("/metrics", tags=["system"], response_class=PlainTextResponse)
    async def metrics() -> PlainTextResponse:
        async with app.state.session_factory() as session:
            lib_count = int((await session.scalar(select(func.count()).select_from(Library))) or 0)
            item_rows = (
                await session.execute(select(Item.kind, func.count()).group_by(Item.kind))
            ).all()
            job_rows = (
                await session.execute(select(Job.status, func.count()).group_by(Job.status))
            ).all()

        lines = [
            "# HELP metashelf_libraries_total Total configured libraries",
            "# TYPE metashelf_libraries_total gauge",
            f"metashelf_libraries_total {lib_count}",
            "# HELP metashelf_items_total Total indexed items by kind",
            "# TYPE metashelf_items_total gauge",
        ]
        for kind, count in item_rows:
            lines.append(f'metashelf_items_total{{kind="{kind}"}} {int(count)}')
        lines.extend(
            [
                "# HELP metashelf_jobs_total Total background jobs by status",
                "# TYPE metashelf_jobs_total gauge",
            ]
        )
        for job_status, count in job_rows:
            lines.append(f'metashelf_jobs_total{{status="{job_status}"}} {int(count)}')

        return PlainTextResponse(
            "\n".join(lines) + "\n",
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(movies.router)
    app.include_router(tv.router)
    app.include_router(music.router)
    app.include_router(ebooks.router)
    app.include_router(comics.router)
    app.include_router(jobs.router)
    app.include_router(settings_router.router)

    return app


app = create_app()
