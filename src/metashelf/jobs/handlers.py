"""Background job handlers."""

import hashlib
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.config import Settings
from metashelf.db.models import Item, Job, Library, SidecarFile
from metashelf.domain.models import (
    EpisodeMetadata,
    ItemKind,
    ItemState,
    MovieMetadata,
    TrackMetadata,
)
from metashelf.matching.comic import auto_match_comic_library
from metashelf.matching.ebook import auto_match_ebook_library
from metashelf.matching.movie import auto_match_movie_item
from metashelf.matching.music import auto_match_music_library
from metashelf.providers.base import LyricsQuery, SubtitleQuery
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.comicvine import ComicVineProvider
from metashelf.providers.coverart import CoverArtArchiveProvider
from metashelf.providers.googlebooks import GoogleBooksProvider
from metashelf.providers.lrclib import LRCLIBProvider
from metashelf.providers.musicbrainz import MusicBrainzProvider
from metashelf.providers.openlibrary import OpenLibraryProvider
from metashelf.providers.opensubtitles import OpenSubtitlesProvider, compute_opensubtitles_hash
from metashelf.providers.tmdb import TMDBProvider
from metashelf.scanner.comic import scan_comic_library
from metashelf.scanner.ebook import scan_ebook_library
from metashelf.scanner.movie import scan_movie_library
from metashelf.scanner.music import scan_music_library
from metashelf.scanner.tv import scan_tv_library
from metashelf.services.paths import resolve_within_root
from metashelf.services.tv_save import fetch_all_episodes_for_show
from metashelf.web.routers.settings import (
    SETTING_LANGUAGE,
    SETTING_MOVIE_NAMING,
    SETTING_TMDB_KEY,
    get_setting_value,
)
from metashelf.writers.lyrics import LyricsExistsError, find_existing_lyrics, write_lyrics_file
from metashelf.writers.subtitles import (
    SubtitleExistsError,
    subtitle_target_path,
    write_subtitle_file,
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
    elif lib.type == "music":
        await scan_music_library(session, lib)
    elif lib.type == "ebook":
        await scan_ebook_library(session, lib)
    elif lib.type == "comic":
        await scan_comic_library(session, lib)

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


async def handle_fetch_subtitles(
    session: AsyncSession,
    job: Job,
    payload: dict[str, Any],
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> None:
    """Fetch subtitles for movies or TV episodes in a library."""
    library_id = int(payload["library_id"])
    lib = await session.get(Library, library_id)
    if lib is None:
        raise ValueError(f"Library {library_id} not found")

    raw_langs = payload.get("languages") or ["en"]
    languages = [str(lang).strip().lower() for lang in raw_langs if str(lang).strip()]
    only_missing = bool(payload.get("only_missing", True))

    target_kind = ItemKind.MOVIE.value if lib.type == "movie" else ItemKind.EPISODE.value
    items = (
        await session.execute(
            select(Item).where(Item.library_id == library_id, Item.kind == target_kind)
        )
    ).scalars().all()

    prov = OpenSubtitlesProvider(
        api_key=settings.opensubtitles_api_key,
        username=settings.opensubtitles_username,
        password=settings.opensubtitles_password,
        http_client=http_client,
        cache=ProviderResponseCache(session),
    )
    root = Path(lib.root_path).resolve()

    job.total = len(items)
    job.progress = 0
    await session.commit()

    for idx, item in enumerate(items, start=1):
        video_path = resolve_within_root(item.rel_path, root)
        movie_hash = compute_opensubtitles_hash(video_path)

        if item.kind == ItemKind.MOVIE.value:
            m_meta = MovieMetadata.model_validate_json(item.metadata_json or "{}")
            base_query = {
                "title": m_meta.title or item.title,
                "year": m_meta.year or item.year,
                "tmdb_id": m_meta.tmdb_id,
                "imdb_id": m_meta.imdb_id,
            }
        else:
            e_meta = EpisodeMetadata.model_validate_json(item.metadata_json or "{}")
            base_query = {
                "title": e_meta.show_title or e_meta.title,
                "year": item.year,
                "tmdb_id": e_meta.tmdb_id,
                "imdb_id": e_meta.imdb_id,
                "season": e_meta.season,
                "episode": e_meta.episode,
            }

        for lang in languages:
            target = subtitle_target_path(video_path, lang)
            if only_missing and target.exists():
                continue

            cands = await prov.search(
                SubtitleQuery(
                    **base_query,  # type: ignore[arg-type]
                    movie_hash=movie_hash,
                    languages=[lang],
                )
            )
            if not cands:
                continue

            dl = await prov.download(cands[0])
            try:
                written = write_subtitle_file(
                    video_path,
                    lang,
                    dl.content,
                    forced=cands[0].forced,
                    hearing_impaired=cands[0].hearing_impaired,
                    overwrite=not only_missing,
                )
                session.add(
                    SidecarFile(
                        item_id=item.id,
                        kind="subtitle",
                        rel_path=written.relative_to(root).as_posix(),
                        lang=lang,
                        format="srt",
                        synced=cands[0].synced,
                        source="opensubtitles",
                        source_id=cands[0].file_id,
                        sha256=hashlib.sha256(written.read_bytes()).hexdigest(),
                    )
                )
            except SubtitleExistsError:
                pass

        job.progress = idx
        await session.commit()


async def handle_fetch_lyrics(
    session: AsyncSession,
    job: Job,
    payload: dict[str, Any],
    http_client: httpx.AsyncClient,
    _settings: Settings,
) -> None:
    """Fetch synced (.lrc) or plain (.txt) lyrics for music tracks in a library."""
    library_id = int(payload["library_id"])
    lib = await session.get(Library, library_id)
    if lib is None:
        raise ValueError(f"Library {library_id} not found")

    only_missing = bool(payload.get("only_missing", True))
    tracks = (
        await session.execute(
            select(Item).where(Item.library_id == library_id, Item.kind == ItemKind.TRACK.value)
        )
    ).scalars().all()

    prov = LRCLIBProvider(
        http_client=http_client,
        cache=ProviderResponseCache(session),
    )
    root = Path(lib.root_path).resolve()

    job.total = len(tracks)
    job.progress = 0
    await session.commit()

    for idx, track in enumerate(tracks, start=1):
        audio_path = resolve_within_root(track.rel_path, root)
        if only_missing and find_existing_lyrics(audio_path) is not None:
            job.progress = idx
            await session.commit()
            continue

        t_meta = TrackMetadata.model_validate_json(track.metadata_json or "{}")
        dur_s = int(t_meta.duration_ms / 1000) if t_meta.duration_ms else None
        cands = await prov.search(
            LyricsQuery(
                title=t_meta.title or track.title,
                artist=t_meta.artist,
                album=t_meta.album,
                duration_seconds=dur_s,
            )
        )
        if cands:
            best = cands[0]
            try:
                written = write_lyrics_file(
                    audio_path,
                    best.text,
                    synced=best.synced,
                    overwrite=not only_missing,
                )
                session.add(
                    SidecarFile(
                        item_id=track.id,
                        kind="lyrics",
                        rel_path=written.relative_to(root).as_posix(),
                        format=best.format,
                        synced=best.synced,
                        source="lrclib",
                        source_id=best.provider_id,
                        sha256=hashlib.sha256(written.read_bytes()).hexdigest(),
                    )
                )
            except LyricsExistsError:
                pass

        job.progress = idx
        await session.commit()


async def handle_auto_match(
    session: AsyncSession,
    job: Job,
    payload: dict[str, Any],
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> None:
    """Auto-match unmatched items in a movie or music library."""
    library_id = int(payload["library_id"])
    lib = await session.get(Library, library_id)
    if lib is None:
        raise ValueError(f"Library {library_id} not found")

    cache = ProviderResponseCache(session)
    if lib.type == "music":
        mb = MusicBrainzProvider(http_client=http_client, cache=cache)
        caa = CoverArtArchiveProvider(http_client=http_client, cache=cache)
        job.total = 1
        job.progress = 0
        await session.commit()
        await auto_match_music_library(session, lib, mb, caa, http_client)
        job.progress = 1
        await session.commit()
        return

    if lib.type == "ebook":
        ol = OpenLibraryProvider(http_client=http_client, cache=cache)
        gb = GoogleBooksProvider(
            http_client=http_client,
            api_key=settings.google_books_api_key,
            cache=cache,
        )
        job.total = 1
        job.progress = 0
        await session.commit()
        await auto_match_ebook_library(session, lib, ol, gb, http_client)
        job.progress = 1
        await session.commit()
        return

    if lib.type == "comic":
        cv = ComicVineProvider(
            api_key=settings.comicvine_api_key,
            http_client=http_client,
            cache=cache,
        )
        job.total = 1
        job.progress = 0
        await session.commit()
        await auto_match_comic_library(session, lib, cv, http_client)
        job.progress = 1
        await session.commit()
        return

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
