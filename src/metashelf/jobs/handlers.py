"""Background job handlers."""

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.config import Settings
from metashelf.db.models import Item, Job, Library
from metashelf.domain.models import ItemKind, ItemState
from metashelf.matching.movie import auto_match_movie_item
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.tmdb import TMDBProvider
from metashelf.scanner.movie import scan_movie_library
from metashelf.scanner.tv import scan_tv_library
from metashelf.services.tv_save import fetch_all_episodes_for_show
from metashelf.web.routers.settings import (
    SETTING_LANGUAGE,
    SETTING_MOVIE_NAMING,
    SETTING_TMDB_KEY,
    get_setting_value,
)


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
    elif lib.type == "tv":
        await scan_tv_library(session, lib)

    job.progress = 1
    await session.commit()


async def handle_fetch_show_episodes(
    session: AsyncSession,
    job: Job,
    payload: dict[str, Any],
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> None:
    """Fetch metadata, NFOs, and artwork for all episodes of a matched show."""
    show_id = int(payload["show_id"])
    show_item = await session.get(Item, show_id)
    if show_item is None:
        raise ValueError(f"Show {show_id} not found")
    lib = await session.get(Library, show_item.library_id)
    if lib is None:
        raise ValueError(f"Library {show_item.library_id} not found")

    api_key = await get_setting_value(session, SETTING_TMDB_KEY, settings.tmdb_api_key)
    lang = await get_setting_value(session, SETTING_LANGUAGE, "en-US")
    cache = ProviderResponseCache(session)
    provider = TMDBProvider(api_key=api_key, http_client=http_client, cache=cache)

    job.total = 1
    job.progress = 0
    await session.commit()

    await fetch_all_episodes_for_show(session, show_item, lib, provider, http_client, lang=lang)
    job.progress = 1
    await session.commit()


async def handle_auto_match(
    session: AsyncSession,
    job: Job,
    payload: dict[str, Any],
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> None:
    """Auto-match all unmatched movies in a library."""
    library_id = int(payload["library_id"])
    lib = await session.get(Library, library_id)
    if lib is None:
        raise ValueError(f"Library {library_id} not found")

    api_key = await get_setting_value(session, SETTING_TMDB_KEY, settings.tmdb_api_key)
    lang = await get_setting_value(session, SETTING_LANGUAGE, "en-US")
    naming = await get_setting_value(session, SETTING_MOVIE_NAMING, "file")
    cache = ProviderResponseCache(session)
    provider = TMDBProvider(api_key=api_key, http_client=http_client, cache=cache)

    items = (
        await session.execute(
            select(Item).where(
                Item.library_id == library_id,
                Item.kind == ItemKind.MOVIE.value,
                Item.state == ItemState.UNMATCHED.value,
            )
        )
    ).scalars().all()

    job.total = len(items)
    job.progress = 0
    await session.commit()

    for idx, item in enumerate(items, start=1):
        await auto_match_movie_item(
            session,
            item,
            lib,
            provider,
            http_client,
            lang=lang,
            naming_scheme=naming,
        )
        job.progress = idx
        await session.commit()
