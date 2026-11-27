"""Background job handlers."""

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.config import Settings
from metashelf.db.models import Job, Library
from metashelf.scanner.movie import scan_movie_library


async def handle_scan_library(
    session: AsyncSession,
    job: Job,
    payload: dict[str, Any],
    _http_client: httpx.AsyncClient,
    _settings: Settings,
) -> None:
    """Scan a configured library by ID."""
    library_id = int(payload["library_id"])
    lib = await session.get(Library, library_id)
    if lib is None:
        raise ValueError(f"Library {library_id} not found")

    job.total = 1
    job.progress = 0
    await session.commit()

    if lib.type == "movie":
        await scan_movie_library(session, lib)

    job.progress = 1
    await session.commit()
