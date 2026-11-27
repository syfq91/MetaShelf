"""TV show/episode sidecar save and batch episode fetch services."""

import json
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import (
    ArtworkType,
    EpisodeMetadata,
    ItemKind,
    ItemState,
    SeasonMetadata,
    ShowMetadata,
)
from metashelf.providers.tmdb import TMDBProvider
from metashelf.readers.kodi_nfo_tv import read_episode_nfo, read_tvshow_nfo
from metashelf.services.paths import resolve_within_root
from metashelf.writers.artwork import ArtworkDownloadError, download_artwork
from metashelf.writers.kodi_nfo_tv import write_episode_nfo, write_tvshow_nfo


async def _upsert_artwork_record(
    session: AsyncSession,
    item_id: int,
    art_type: str,
    rel_path: str,
    source_url: str,
    width: int,
    height: int,
) -> None:
    existing = (
        await session.execute(
            select(Artwork).where(Artwork.item_id == item_id, Artwork.type == art_type)
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Artwork(
                item_id=item_id,
                type=art_type,
                rel_path=rel_path,
                source_url=source_url,
                width=width,
                height=height,
            )
        )
    else:
        existing.rel_path = rel_path
        existing.source_url = source_url
        existing.width = width
        existing.height = height


async def save_show_to_disk(
    session: AsyncSession,
    show_item: Item,
    library: Library,
) -> Path:
    """Write tvshow.nfo atomically, preserving unknown XML elements."""
    root = Path(library.root_path).resolve()
    show_dir = resolve_within_root(show_item.rel_path, root)
    nfo_path = show_dir / "tvshow.nfo"

    unknown = None
    if nfo_path.is_file():
        try:
            unknown = read_tvshow_nfo(nfo_path).unknown_elements
        except Exception:
            unknown = None

    meta = ShowMetadata.model_validate_json(show_item.metadata_json or "{}")
    pids: dict[str, str] = json.loads(show_item.provider_ids_json or "{}")
    if pids.get("tmdb"):
        meta.tmdb_id = pids["tmdb"]
    if pids.get("tvdb"):
        meta.tvdb_id = pids["tvdb"]
    if pids.get("imdb"):
        meta.imdb_id = pids["imdb"]

    write_tvshow_nfo(nfo_path, meta, unknown_elements=unknown)
    show_item.title = meta.title or show_item.title
    show_item.year = meta.year
    show_item.metadata_json = meta.model_dump_json()
    show_item.sidecar_mtime = nfo_path.stat().st_mtime

    arts = (
        await session.execute(select(Artwork).where(Artwork.item_id == show_item.id))
    ).scalars().all()
    has_poster = any(a.type == ArtworkType.POSTER.value for a in arts)
    show_item.state = ItemState.COMPLETE.value if has_poster else ItemState.MATCHED.value
    await session.commit()
    return nfo_path


async def save_episode_to_disk(
    session: AsyncSession,
    ep_item: Item,
    library: Library,
    episode_blocks: list[EpisodeMetadata] | None = None,
) -> Path:
    """Write <episode>.nfo atomically, supporting multi-episode stacked blocks."""
    root = Path(library.root_path).resolve()
    video_path = resolve_within_root(ep_item.rel_path, root)
    nfo_path = video_path.with_suffix(".nfo")

    unknown = None
    if nfo_path.is_file():
        try:
            unknown = read_episode_nfo(nfo_path).unknown_elements
        except Exception:
            unknown = None

    meta = EpisodeMetadata.model_validate_json(ep_item.metadata_json or "{}")
    blocks = episode_blocks or [meta]
    write_episode_nfo(nfo_path, blocks, unknown_elements=unknown)

    ep_item.title = meta.title or ep_item.title
    ep_item.metadata_json = meta.model_dump_json()
    ep_item.sidecar_mtime = nfo_path.stat().st_mtime
    ep_item.state = ItemState.COMPLETE.value
    await session.commit()
    return nfo_path


async def fetch_all_episodes_for_show(
    session: AsyncSession,
    show_item: Item,
    library: Library,
    provider: TMDBProvider,
    http_client: httpx.AsyncClient,
    lang: str = "en-US",
) -> int:
    """Fetch show artwork, season posters, and all episode NFOs + thumbs for a matched show."""
    pids: dict[str, str] = json.loads(show_item.provider_ids_json or "{}")
    tmdb_id = pids.get("tmdb")
    if not tmdb_id:
        raise ValueError(f"Show '{show_item.title}' is not matched to a TMDB ID.")

    root = Path(library.root_path).resolve()
    show_dir = resolve_within_root(show_item.rel_path, root)

    # 1. Ensure show-level poster & fanart
    show_art_cands = await provider.artwork("show", tmdb_id)
    for art_type, filename in [
        (ArtworkType.POSTER.value, "poster.jpg"),
        (ArtworkType.FANART.value, "fanart.jpg"),
    ]:
        cand = next((a for a in show_art_cands if a.type == art_type), None)
        if cand is not None:
            target = show_dir / filename
            try:
                dl = await download_artwork(http_client, cand.url, target)
                await _upsert_artwork_record(
                    session,
                    show_item.id,
                    art_type,
                    dl.path.relative_to(root).as_posix(),
                    cand.url,
                    dl.width,
                    dl.height,
                )
            except ArtworkDownloadError:
                pass

    await save_show_to_disk(session, show_item, library)

    # 2. Iterate seasons and fetch episodes + season posters
    seasons = (
        await session.execute(
            select(Item)
            .where(Item.parent_id == show_item.id, Item.kind == ItemKind.SEASON.value)
            .order_by(Item.rel_path)
        )
    ).scalars().all()

    updated_episodes = 0
    for season_item in seasons:
        s_meta = SeasonMetadata.model_validate_json(season_item.metadata_json or "{}")
        s_num = s_meta.season_number

        # Season poster
        s_arts = await provider.season_artwork(tmdb_id, s_num)
        if s_arts:
            s_target = show_dir / f"season{s_num:02d}-poster.jpg"
            try:
                dl = await download_artwork(http_client, s_arts[0].url, s_target)
                await _upsert_artwork_record(
                    session,
                    season_item.id,
                    ArtworkType.POSTER.value,
                    dl.path.relative_to(root).as_posix(),
                    s_arts[0].url,
                    dl.width,
                    dl.height,
                )
                season_item.state = ItemState.COMPLETE.value
            except ArtworkDownloadError:
                pass

        # Fetch season episodes from TMDB
        remote_eps = await provider.fetch_season_episodes(
            tmdb_id,
            s_num,
            show_title=show_item.title,
            lang=lang,
        )
        by_ep_num: dict[int, EpisodeMetadata] = {ep.episode: ep for ep in remote_eps}

        local_eps = (
            await session.execute(
                select(Item)
                .where(Item.parent_id == season_item.id, Item.kind == ItemKind.EPISODE.value)
                .order_by(Item.rel_path)
            )
        ).scalars().all()

        for ep_item in local_eps:
            local_meta = EpisodeMetadata.model_validate_json(ep_item.metadata_json or "{}")
            ep_nums = local_meta.episodes or [local_meta.episode]
            matched_blocks = [by_ep_num[n] for n in ep_nums if n in by_ep_num]
            if not matched_blocks:
                continue

            primary = matched_blocks[0].model_copy()
            primary.episodes = ep_nums
            if len(matched_blocks) > 1:
                primary.title = " / ".join(b.title for b in matched_blocks)

            ep_item.title = primary.title
            ep_item.metadata_json = primary.model_dump_json()
            if primary.tmdb_id:
                ep_item.provider_ids_json = json.dumps({"tmdb": primary.tmdb_id})

            # Download episode thumb
            if primary.thumb_url:
                video_path = resolve_within_root(ep_item.rel_path, root)
                thumb_target = video_path.parent / f"{video_path.stem}-thumb.jpg"
                try:
                    dl = await download_artwork(http_client, primary.thumb_url, thumb_target)
                    await _upsert_artwork_record(
                        session,
                        ep_item.id,
                        ArtworkType.THUMB.value,
                        dl.path.relative_to(root).as_posix(),
                        primary.thumb_url,
                        dl.width,
                        dl.height,
                    )
                except ArtworkDownloadError:
                    pass

            await save_episode_to_disk(session, ep_item, library, episode_blocks=matched_blocks)
            updated_episodes += 1

    await session.commit()
    return updated_episodes
