"""Movie sidecar save, revert, and path helpers."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, ItemState, MovieMetadata
from metashelf.readers.kodi_nfo_movie import read_movie_nfo
from metashelf.scanner.movie import find_movie_artwork, find_movie_nfo
from metashelf.scanner.parser import parse_movie_filename
from metashelf.services.paths import resolve_within_root
from metashelf.writers.kodi_nfo_movie import write_movie_nfo


def resolve_movie_nfo_target(video_path: Path, naming_scheme: str = "file") -> Path:
    """Determine target NFO path for a movie based on naming scheme."""
    if naming_scheme == "folder":
        return video_path.parent / "movie.nfo"
    return video_path.with_suffix(".nfo")


def resolve_movie_artwork_target(
    video_path: Path,
    art_type: str,
    naming_scheme: str = "file",
    ext: str = ".jpg",
) -> Path:
    """Determine target artwork path for a movie based on naming scheme."""
    if naming_scheme == "folder":
        filename = "poster" if art_type == ArtworkType.POSTER.value else "fanart"
        return video_path.parent / f"{filename}{ext}"
    suffix = "poster" if art_type == ArtworkType.POSTER.value else "fanart"
    return video_path.parent / f"{video_path.stem}-{suffix}{ext}"


async def save_movie_to_disk(
    session: AsyncSession,
    item: Item,
    library: Library,
    naming_scheme: str = "file",
) -> Path:
    """Write movie NFO sidecar atomically, preserving unknown XML tags."""
    root = Path(library.root_path).resolve()
    video_path = resolve_within_root(item.rel_path, root)
    existing_nfo = find_movie_nfo(video_path)

    unknown_elements = None
    if existing_nfo is not None and existing_nfo.is_file():
        try:
            unknown_elements = read_movie_nfo(existing_nfo).unknown_elements
        except Exception:
            unknown_elements = None

    target_nfo = existing_nfo or resolve_movie_nfo_target(video_path, naming_scheme)
    meta = MovieMetadata.model_validate_json(item.metadata_json)

    # Sync provider IDs into metadata
    provider_ids: dict[str, str] = json.loads(item.provider_ids_json or "{}")
    if provider_ids.get("tmdb"):
        meta.tmdb_id = provider_ids["tmdb"]
    if provider_ids.get("imdb"):
        meta.imdb_id = provider_ids["imdb"]

    write_movie_nfo(target_nfo, meta, unknown_elements=unknown_elements)

    item.title = meta.title or item.title
    item.year = meta.year
    item.metadata_json = meta.model_dump_json()
    item.sidecar_mtime = target_nfo.stat().st_mtime

    artworks = (
        await session.execute(select(Artwork).where(Artwork.item_id == item.id))
    ).scalars().all()
    has_poster = any(a.type == ArtworkType.POSTER.value for a in artworks)
    item.state = ItemState.COMPLETE.value if has_poster else ItemState.MATCHED.value
    await session.commit()
    return target_nfo


async def revert_movie_from_disk(
    session: AsyncSession,
    item: Item,
    library: Library,
) -> None:
    """Reload movie metadata from existing NFO on disk, or fallback to filename parse."""
    root = Path(library.root_path).resolve()
    video_path = resolve_within_root(item.rel_path, root)
    nfo_path = find_movie_nfo(video_path)
    parsed_name = parse_movie_filename(item.rel_path)

    if nfo_path is not None and nfo_path.is_file():
        parsed_nfo = read_movie_nfo(nfo_path)
        meta = parsed_nfo.metadata
        if not meta.title:
            meta.title = parsed_name.title
        if meta.year is None:
            meta.year = parsed_name.year
        provider_ids: dict[str, str] = {}
        if meta.tmdb_id:
            provider_ids["tmdb"] = meta.tmdb_id
        if meta.imdb_id:
            provider_ids["imdb"] = meta.imdb_id
        item.provider_ids_json = json.dumps(provider_ids)
        item.sidecar_mtime = nfo_path.stat().st_mtime
        art_on_disk = find_movie_artwork(video_path)
        item.state = (
            ItemState.COMPLETE.value
            if ArtworkType.POSTER.value in art_on_disk
            else ItemState.MATCHED.value
        )
    else:
        meta = MovieMetadata(title=parsed_name.title, year=parsed_name.year)
        item.provider_ids_json = "{}"
        item.sidecar_mtime = None
        item.state = ItemState.UNMATCHED.value

    item.title = meta.title
    item.year = meta.year
    item.metadata_json = meta.model_dump_json()
    await session.commit()
