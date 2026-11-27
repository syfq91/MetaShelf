"""TV show, season, and episode library scanner."""

import json
from datetime import UTC, datetime
from pathlib import Path

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
from metashelf.readers.kodi_nfo_tv import read_episode_nfo, read_tvshow_nfo
from metashelf.scanner.movie import VIDEO_EXTENSIONS, ScanStats, _is_ignored_video
from metashelf.scanner.parser import parse_show_folder_name, parse_tv_episode_filename


def _show_dir_for_episode(root: Path, video_path: Path) -> Path:
    """Resolve the show folder directly under root."""
    rel_parts = video_path.relative_to(root).parts
    if len(rel_parts) >= 2:
        return root / rel_parts[0]
    return video_path.parent


def find_tvshow_artwork(show_dir: Path) -> dict[str, Path]:
    """Find existing show-level artwork (poster, fanart, banner, logo)."""
    found: dict[str, Path] = {}
    for art_type, names in [
        (ArtworkType.POSTER.value, ["poster.jpg", "poster.png"]),
        (ArtworkType.FANART.value, ["fanart.jpg", "fanart.png"]),
        (ArtworkType.BANNER.value, ["banner.jpg", "banner.png"]),
        (ArtworkType.LOGO.value, ["clearlogo.png", "logo.png"]),
    ]:
        for name in names:
            p = show_dir / name
            if p.is_file():
                found[art_type] = p
                break
    return found


def find_season_poster(show_dir: Path, season_number: int) -> Path | None:
    """Find existing seasonNN-poster.jpg (or season-specials-poster.jpg for season 0)."""
    candidates = [
        show_dir / f"season{season_number:02d}-poster.jpg",
        show_dir / f"season{season_number:02d}-poster.png",
    ]
    if season_number == 0:
        candidates.append(show_dir / "season-specials-poster.jpg")
    for c in candidates:
        if c.is_file():
            return c
    return None


def find_episode_thumb(video_path: Path) -> Path | None:
    """Find existing <episode>-thumb.jpg next to the episode video."""
    for ext in (".jpg", ".png"):
        p = video_path.parent / f"{video_path.stem}-thumb{ext}"
        if p.is_file():
            return p
    return None


async def _upsert_artwork(
    session: AsyncSession,
    item_id: int,
    art_type: str,
    rel_path: str,
) -> None:
    existing = (
        await session.execute(
            select(Artwork).where(Artwork.item_id == item_id, Artwork.type == art_type)
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(Artwork(item_id=item_id, type=art_type, rel_path=rel_path))
    else:
        existing.rel_path = rel_path


async def scan_tv_library(session: AsyncSession, library: Library) -> ScanStats:
    """Scan a TV library root incrementally into show -> season -> episode hierarchy."""
    root = Path(library.root_path).resolve()
    stats = ScanStats()
    if not root.exists() or not root.is_dir():
        return stats

    existing_rows = (
        await session.execute(select(Item).where(Item.library_id == library.id))
    ).scalars().all()
    by_rel_path: dict[str, Item] = {item.rel_path: item for item in existing_rows}

    video_files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTENSIONS
        and not p.name.startswith(".")
        and not _is_ignored_video(p)
    )

    now = datetime.now(UTC)
    shows_seen: dict[str, Item] = {}
    seasons_seen: dict[str, Item] = {}

    for video_path in video_files:
        show_dir = _show_dir_for_episode(root, video_path)
        show_rel = show_dir.relative_to(root).as_posix()
        parsed_ep = parse_tv_episode_filename(video_path.relative_to(root).as_posix())

        # 1. Ensure Show Item (adopt tvshow.nfo if present)
        show_item = shows_seen.get(show_rel) or by_rel_path.get(show_rel)
        if show_item is None:
            parsed_show = parse_show_folder_name(show_dir.name)
            show_meta = ShowMetadata(
                title=parsed_show.title or parsed_ep.show_title,
                year=parsed_show.year or parsed_ep.year,
            )
            show_provider_ids: dict[str, str] = {}
            show_state = ItemState.UNMATCHED.value
            tvshow_nfo = show_dir / "tvshow.nfo"
            tvshow_mtime = tvshow_nfo.stat().st_mtime if tvshow_nfo.is_file() else None
            if tvshow_nfo.is_file():
                try:
                    show_meta = read_tvshow_nfo(tvshow_nfo).metadata
                    if show_meta.tmdb_id:
                        show_provider_ids["tmdb"] = show_meta.tmdb_id
                    if show_meta.tvdb_id:
                        show_provider_ids["tvdb"] = show_meta.tvdb_id
                    if show_meta.imdb_id:
                        show_provider_ids["imdb"] = show_meta.imdb_id
                    if show_provider_ids or show_meta.plot:
                        show_state = ItemState.MATCHED.value
                except Exception:
                    show_state = ItemState.ERROR.value

            show_item = Item(
                library_id=library.id,
                kind=ItemKind.SHOW.value,
                rel_path=show_rel,
                title=show_meta.title,
                year=show_meta.year,
                state=show_state,
                provider_ids_json=json.dumps(show_provider_ids),
                metadata_json=show_meta.model_dump_json(),
                sidecar_mtime=tvshow_mtime,
                scanned_at=now,
            )
            session.add(show_item)
            await session.flush()
            by_rel_path[show_rel] = show_item
        shows_seen[show_rel] = show_item

        for art_type, art_path in find_tvshow_artwork(show_dir).items():
            await _upsert_artwork(
                session,
                show_item.id,
                art_type,
                art_path.relative_to(root).as_posix(),
            )

        # 2. Ensure Season Item
        season_num = parsed_ep.season
        season_rel = f"{show_rel}::season:{season_num:02d}"
        season_item = seasons_seen.get(season_rel) or by_rel_path.get(season_rel)
        if season_item is None:
            season_title = "Specials" if season_num == 0 else f"Season {season_num:02d}"
            season_meta = SeasonMetadata(season_number=season_num, title=season_title)
            season_item = Item(
                library_id=library.id,
                kind=ItemKind.SEASON.value,
                parent_id=show_item.id,
                rel_path=season_rel,
                title=season_title,
                year=show_item.year,
                state=ItemState.UNMATCHED.value,
                provider_ids_json="{}",
                metadata_json=season_meta.model_dump_json(),
                scanned_at=now,
            )
            session.add(season_item)
            await session.flush()
            by_rel_path[season_rel] = season_item
        seasons_seen[season_rel] = season_item

        season_poster = find_season_poster(show_dir, season_num)
        if season_poster is not None:
            await _upsert_artwork(
                session,
                season_item.id,
                ArtworkType.POSTER.value,
                season_poster.relative_to(root).as_posix(),
            )

        # 3. Episode Item (incremental mtime/size check)
        ep_rel = video_path.relative_to(root).as_posix()
        stat = video_path.stat()
        ep_nfo = video_path.with_suffix(".nfo")
        nfo_mtime = ep_nfo.stat().st_mtime if ep_nfo.is_file() else None

        existing_ep = by_rel_path.get(ep_rel)
        if (
            existing_ep is not None
            and existing_ep.media_mtime == stat.st_mtime
            and existing_ep.media_size == stat.st_size
            and existing_ep.sidecar_mtime == nfo_mtime
        ):
            stats.skipped += 1
            continue

        ep_nums = parsed_ep.episodes
        ep_label = f"S{season_num:02d}" + "".join(f"E{e:02d}" for e in ep_nums)
        ep_meta = EpisodeMetadata(
            title=ep_label,
            show_title=show_item.title,
            season=season_num,
            episode=ep_nums[0],
            episodes=ep_nums,
        )
        ep_state = ItemState.UNMATCHED.value
        ep_provider_ids: dict[str, str] = {}
        if ep_nfo.is_file():
            try:
                parsed_nfo = read_episode_nfo(ep_nfo)
                first_ep = parsed_nfo.episodes[0]
                first_ep.episodes = [e.episode for e in parsed_nfo.episodes] or ep_nums
                ep_meta = first_ep
                if ep_meta.tmdb_id:
                    ep_provider_ids["tmdb"] = ep_meta.tmdb_id
                if ep_meta.tvdb_id:
                    ep_provider_ids["tvdb"] = ep_meta.tvdb_id
                if ep_meta.imdb_id:
                    ep_provider_ids["imdb"] = ep_meta.imdb_id
                if ep_provider_ids or ep_meta.plot:
                    ep_state = ItemState.MATCHED.value
            except Exception:
                ep_state = ItemState.ERROR.value

        if existing_ep is None:
            ep_item = Item(
                library_id=library.id,
                kind=ItemKind.EPISODE.value,
                parent_id=season_item.id,
                rel_path=ep_rel,
                title=ep_meta.title,
                year=show_item.year,
                state=ep_state,
                provider_ids_json=json.dumps(ep_provider_ids),
                metadata_json=ep_meta.model_dump_json(),
                sidecar_mtime=nfo_mtime,
                media_mtime=stat.st_mtime,
                media_size=stat.st_size,
                scanned_at=now,
            )
            session.add(ep_item)
            await session.flush()
            by_rel_path[ep_rel] = ep_item
            stats.added += 1
        else:
            ep_item = existing_ep
            if existing_ep.state != ItemState.DIRTY.value:
                existing_ep.title = ep_meta.title
                existing_ep.metadata_json = ep_meta.model_dump_json()
            existing_ep.parent_id = season_item.id
            existing_ep.sidecar_mtime = nfo_mtime
            existing_ep.media_mtime = stat.st_mtime
            existing_ep.media_size = stat.st_size
            existing_ep.scanned_at = now
            stats.updated += 1

        thumb = find_episode_thumb(video_path)
        if thumb is not None:
            await _upsert_artwork(
                session,
                ep_item.id,
                ArtworkType.THUMB.value,
                thumb.relative_to(root).as_posix(),
            )

    await session.commit()
    return stats
