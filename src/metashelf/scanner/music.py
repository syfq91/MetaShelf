"""Music library scanner using folder structure and mutagen audio tags."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import (
    AlbumMetadata,
    ArtistMetadata,
    ArtworkType,
    ItemKind,
    ItemState,
    TrackInfo,
    TrackMetadata,
)
from metashelf.scanner.movie import ScanStats

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wav", ".wv"}
_YEAR_RE = re.compile(r"\((\d{4})\)\s*$")
_TRACK_PREFIX_RE = re.compile(r"^(\d{1,3})\s*[-._]\s*(.+)$")


def _first_tag(tags: Any, key: str) -> str:
    if not tags:
        return ""
    val = tags.get(key)
    if isinstance(val, list) and val:
        return str(val[0]).strip()
    if val is not None:
        return str(val).strip()
    return ""


def _parse_int_slash(raw: str, default: int = 1) -> int:
    if not raw:
        return default
    head = raw.split("/")[0].strip()
    return int(head) if head.isdigit() else default


def _parse_year(raw: str) -> int | None:
    if raw and len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return None


def _strip_folder_year(name: str) -> tuple[str, int | None]:
    m = _YEAR_RE.search(name)
    if m:
        return name[: m.start()].strip(), int(m.group(1))
    return name.strip(), None


def read_audio_tags(path: Path) -> TrackMetadata:
    """Read embedded audio tags via mutagen with filename fallback."""
    track_num = 1
    title = path.stem
    m = _TRACK_PREFIX_RE.match(path.stem)
    if m:
        track_num = int(m.group(1))
        title = m.group(2).strip()

    try:
        audio = MutagenFile(path, easy=True)
    except Exception:
        audio = None

    if audio is None:
        return TrackMetadata(title=title, track_number=track_num)

    duration_ms = (
        int(audio.info.length * 1000)
        if getattr(audio, "info", None) and getattr(audio.info, "length", None)
        else None
    )
    tags = getattr(audio, "tags", None)
    tag_title = _first_tag(tags, "title") or title
    tag_artist = _first_tag(tags, "albumartist") or _first_tag(tags, "artist")
    tag_album = _first_tag(tags, "album")
    tag_track = _parse_int_slash(_first_tag(tags, "tracknumber"), default=track_num)
    tag_disc = _parse_int_slash(_first_tag(tags, "discnumber"), default=1)
    tag_year = _parse_year(_first_tag(tags, "date") or _first_tag(tags, "year"))

    return TrackMetadata(
        title=tag_title,
        artist=tag_artist,
        album=tag_album,
        track_number=tag_track,
        disc_number=tag_disc,
        duration_ms=duration_ms,
        year=tag_year,
    )


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


async def scan_music_library(session: AsyncSession, library: Library) -> ScanStats:
    """Scan a music library root incrementally into artist -> album -> track hierarchy."""
    root = Path(library.root_path).resolve()
    stats = ScanStats()
    if not root.exists() or not root.is_dir():
        return stats

    existing_rows = (
        await session.execute(select(Item).where(Item.library_id == library.id))
    ).scalars().all()
    by_rel_path: dict[str, Item] = {item.rel_path: item for item in existing_rows}

    audio_files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in AUDIO_EXTENSIONS
        and not p.name.startswith(".")
    )

    now = datetime.now(UTC)
    artists_seen: dict[str, Item] = {}
    albums_seen: dict[str, Item] = {}
    album_tracks_map: dict[int, list[TrackInfo]] = {}

    for audio_path in audio_files:
        rel_parts = audio_path.relative_to(root).parts
        if len(rel_parts) >= 3:
            artist_dir = root / rel_parts[0]
            album_dir = root / rel_parts[0] / rel_parts[1]
        elif len(rel_parts) == 2:
            artist_dir = root
            album_dir = root / rel_parts[0]
        else:
            artist_dir = root
            album_dir = root

        track_meta = read_audio_tags(audio_path)

        # 1. Artist Item
        artist_rel = artist_dir.relative_to(root).as_posix() if artist_dir != root else "__root__"
        artist_item = artists_seen.get(artist_rel) or by_rel_path.get(artist_rel)
        if artist_item is None:
            artist_name = (
                track_meta.artist
                if artist_dir == root and track_meta.artist
                else artist_dir.name
            )
            a_meta = ArtistMetadata(name=artist_name, sort_name=artist_name)
            artist_item = Item(
                library_id=library.id,
                kind=ItemKind.ARTIST.value,
                rel_path=artist_rel,
                title=a_meta.name,
                state=ItemState.UNMATCHED.value,
                provider_ids_json="{}",
                metadata_json=a_meta.model_dump_json(),
                scanned_at=now,
            )
            session.add(artist_item)
            await session.flush()
            by_rel_path[artist_rel] = artist_item
        artists_seen[artist_rel] = artist_item

        for art_type, names in [
            (ArtworkType.COVER.value, ["folder.jpg", "folder.png", "poster.jpg"]),
            (ArtworkType.FANART.value, ["fanart.jpg", "fanart.png"]),
        ]:
            for fname in names:
                p = artist_dir / fname
                if p.is_file():
                    await _upsert_artwork(
                        session, artist_item.id, art_type, p.relative_to(root).as_posix()
                    )
                    break

        # 2. Album Item
        album_rel = album_dir.relative_to(root).as_posix() if album_dir != root else "__album__"
        album_item = albums_seen.get(album_rel) or by_rel_path.get(album_rel)
        if album_item is None:
            folder_title, folder_year = _strip_folder_year(album_dir.name)
            album_title = track_meta.album or folder_title
            album_year = track_meta.year or folder_year
            alb_meta = AlbumMetadata(
                title=album_title,
                artist=artist_item.title,
                year=album_year,
            )
            album_item = Item(
                library_id=library.id,
                kind=ItemKind.ALBUM.value,
                parent_id=artist_item.id,
                rel_path=album_rel,
                title=alb_meta.title,
                year=alb_meta.year,
                state=ItemState.UNMATCHED.value,
                provider_ids_json="{}",
                metadata_json=alb_meta.model_dump_json(),
                scanned_at=now,
            )
            session.add(album_item)
            await session.flush()
            by_rel_path[album_rel] = album_item
        albums_seen[album_rel] = album_item

        for fname in ("folder.jpg", "cover.jpg", "folder.png", "cover.png"):
            p = album_dir / fname
            if p.is_file():
                await _upsert_artwork(
                    session,
                    album_item.id,
                    ArtworkType.COVER.value,
                    p.relative_to(root).as_posix(),
                )
                break

        album_tracks_map.setdefault(album_item.id, []).append(
            TrackInfo(
                position=track_meta.track_number,
                disc=track_meta.disc_number,
                title=track_meta.title,
                duration_ms=track_meta.duration_ms,
            )
        )

        # 3. Track Item (incremental mtime/size check)
        track_rel = audio_path.relative_to(root).as_posix()
        stat = audio_path.stat()
        existing_track = by_rel_path.get(track_rel)
        if (
            existing_track is not None
            and existing_track.media_mtime == stat.st_mtime
            and existing_track.media_size == stat.st_size
        ):
            stats.skipped += 1
            continue

        if existing_track is None:
            t_item = Item(
                library_id=library.id,
                kind=ItemKind.TRACK.value,
                parent_id=album_item.id,
                rel_path=track_rel,
                title=track_meta.title,
                year=track_meta.year,
                state=ItemState.COMPLETE.value,
                provider_ids_json=json.dumps({}),
                metadata_json=track_meta.model_dump_json(),
                media_mtime=stat.st_mtime,
                media_size=stat.st_size,
                scanned_at=now,
            )
            session.add(t_item)
            await session.flush()
            by_rel_path[track_rel] = t_item
            stats.added += 1
        else:
            existing_track.title = track_meta.title
            existing_track.year = track_meta.year
            existing_track.metadata_json = track_meta.model_dump_json()
            existing_track.media_mtime = stat.st_mtime
            existing_track.media_size = stat.st_size
            existing_track.scanned_at = now
            stats.updated += 1

    # Sync track lists into AlbumMetadata for disambiguation
    for alb_id, t_list in album_tracks_map.items():
        alb = await session.get(Item, alb_id)
        if alb is not None and alb.state != ItemState.DIRTY.value:
            alb_meta = AlbumMetadata.model_validate_json(alb.metadata_json or "{}")
            alb_meta.tracks = sorted(t_list, key=lambda t: (t.disc, t.position))
            alb.metadata_json = alb_meta.model_dump_json()

    await session.commit()
    return stats
