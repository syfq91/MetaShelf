"""Movie library scanner and NFO adoption."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, ItemKind, ItemState, MovieMetadata
from metashelf.readers.kodi_nfo_movie import read_movie_nfo
from metashelf.scanner.parser import parse_movie_filename

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".ts", ".webm"}
IGNORED_FILENAMES = {"sample", "trailer"}


@dataclass
class ScanStats:
    """Counts from a library scan run."""

    added: int = 0
    updated: int = 0
    skipped: int = 0


def find_movie_nfo(video_path: Path) -> Path | None:
    """Find an existing NFO sidecar for a movie file (<stem>.nfo or movie.nfo)."""
    by_file = video_path.with_suffix(".nfo")
    if by_file.is_file():
        return by_file
    by_folder = video_path.parent / "movie.nfo"
    if by_folder.is_file():
        return by_folder
    return None


def find_movie_artwork(video_path: Path) -> dict[str, Path]:
    """Find existing poster/fanart files next to a movie."""
    found: dict[str, Path] = {}
    stem = video_path.stem
    parent = video_path.parent

    for art_type, candidates in [
        (
            ArtworkType.POSTER.value,
            [parent / f"{stem}-poster.jpg", parent / f"{stem}-poster.png", parent / "poster.jpg"],
        ),
        (
            ArtworkType.FANART.value,
            [parent / f"{stem}-fanart.jpg", parent / f"{stem}-fanart.png", parent / "fanart.jpg"],
        ),
    ]:
        for c in candidates:
            if c.is_file():
                found[art_type] = c
                break
    return found


def _is_ignored_video(path: Path) -> bool:
    stem_lower = path.stem.lower()
    return any(tok == stem_lower or stem_lower.endswith(f"-{tok}") for tok in IGNORED_FILENAMES)


async def scan_movie_library(session: AsyncSession, library: Library) -> ScanStats:
    """Scan a movie library root incrementally and adopt existing NFO/artwork."""
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

    for video_path in video_files:
        rel_path = video_path.relative_to(root).as_posix()
        stat = video_path.stat()
        nfo_path = find_movie_nfo(video_path)
        nfo_mtime = nfo_path.stat().st_mtime if nfo_path else None

        existing = by_rel_path.get(rel_path)
        if (
            existing is not None
            and existing.media_mtime == stat.st_mtime
            and existing.media_size == stat.st_size
            and existing.sidecar_mtime == nfo_mtime
        ):
            stats.skipped += 1
            continue

        parsed = parse_movie_filename(rel_path)
        meta = MovieMetadata(title=parsed.title, year=parsed.year)
        provider_ids: dict[str, str] = {}
        state = ItemState.UNMATCHED.value

        if nfo_path is not None:
            try:
                parsed_nfo = read_movie_nfo(nfo_path)
                meta = parsed_nfo.metadata
                if not meta.title:
                    meta.title = parsed.title
                if meta.year is None:
                    meta.year = parsed.year
                if meta.tmdb_id:
                    provider_ids["tmdb"] = meta.tmdb_id
                if meta.imdb_id:
                    provider_ids["imdb"] = meta.imdb_id
                state = (
                    ItemState.MATCHED.value
                    if provider_ids or meta.plot
                    else ItemState.UNMATCHED.value
                )
            except Exception:
                state = ItemState.ERROR.value

        if existing is None:
            item = Item(
                library_id=library.id,
                kind=ItemKind.MOVIE.value,
                rel_path=rel_path,
                title=meta.title,
                year=meta.year,
                state=state,
                provider_ids_json=json.dumps(provider_ids),
                metadata_json=meta.model_dump_json(),
                sidecar_mtime=nfo_mtime,
                media_mtime=stat.st_mtime,
                media_size=stat.st_size,
                scanned_at=now,
            )
            session.add(item)
            await session.flush()
            stats.added += 1
        else:
            item = existing
            # Never overwrite manual dirty edits unless cleared
            if existing.state != ItemState.DIRTY.value:
                existing.title = meta.title
                existing.year = meta.year
                existing.metadata_json = meta.model_dump_json()
                if provider_ids:
                    existing.provider_ids_json = json.dumps(provider_ids)
                    existing.state = state
            existing.sidecar_mtime = nfo_mtime
            existing.media_mtime = stat.st_mtime
            existing.media_size = stat.st_size
            existing.scanned_at = now
            stats.updated += 1

        # Sync artwork records found on disk
        art_on_disk = find_movie_artwork(video_path)
        if art_on_disk:
            existing_art = {
                a.type: a
                for a in (
                    await session.execute(select(Artwork).where(Artwork.item_id == item.id))
                ).scalars().all()
            }
            for art_type, art_path in art_on_disk.items():
                art_rel = art_path.relative_to(root).as_posix()
                if art_type in existing_art:
                    existing_art[art_type].rel_path = art_rel
                else:
                    session.add(Artwork(item_id=item.id, type=art_type, rel_path=art_rel))

            if (
                nfo_path is not None
                and ArtworkType.POSTER.value in art_on_disk
                and item.state == ItemState.MATCHED.value
            ):
                item.state = ItemState.COMPLETE.value

    await session.commit()
    return stats
