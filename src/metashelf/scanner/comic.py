"""Comic (.cbz) library scanner with embedded ComicInfo.xml and sidecar adoption."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, ComicMetadata, ItemKind, ItemState
from metashelf.readers.comicinfo_xml import read_cbz_embedded_comicinfo, read_comicinfo_file
from metashelf.scanner.movie import ScanStats
from metashelf.scanner.parser import parse_comic_filename


async def scan_comic_library(session: AsyncSession, library: Library) -> ScanStats:
    """Scan a comic library root for .cbz files incrementally."""
    root = Path(library.root_path).resolve()
    stats = ScanStats()
    if not root.exists() or not root.is_dir():
        return stats

    existing_rows = (
        await session.execute(select(Item).where(Item.library_id == library.id))
    ).scalars().all()
    by_rel_path: dict[str, Item] = {item.rel_path: item for item in existing_rows}

    cbz_files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() == ".cbz" and not p.name.startswith(".")
    )
    now = datetime.now(UTC)

    for cbz_path in cbz_files:
        rel_path = cbz_path.relative_to(root).as_posix()
        stat = cbz_path.stat()
        sidecar_xml = cbz_path.with_suffix(".xml")
        xml_mtime = sidecar_xml.stat().st_mtime if sidecar_xml.is_file() else None

        existing = by_rel_path.get(rel_path)
        if (
            existing is not None
            and existing.media_mtime == stat.st_mtime
            and existing.media_size == stat.st_size
            and existing.sidecar_mtime == xml_mtime
        ):
            stats.skipped += 1
            continue

        parsed = parse_comic_filename(rel_path)
        meta = ComicMetadata(
            title=cbz_path.stem,
            series=parsed.series,
            number=parsed.number,
            volume=parsed.volume,
            year=parsed.year,
        )
        provider_ids: dict[str, str] = {}
        state = ItemState.UNMATCHED.value

        # Sidecar <comic>.xml wins when both exist
        if sidecar_xml.is_file():
            try:
                meta = read_comicinfo_file(sidecar_xml).metadata
                if not meta.series:
                    meta.series = parsed.series
                if not meta.number:
                    meta.number = parsed.number
                if meta.summary or meta.publisher or meta.writers:
                    state = ItemState.MATCHED.value
            except Exception:
                state = ItemState.ERROR.value
        else:
            try:
                embedded = read_cbz_embedded_comicinfo(cbz_path)
                if embedded is not None:
                    meta = embedded.metadata
                    if not meta.series:
                        meta.series = parsed.series
                    if not meta.number:
                        meta.number = parsed.number
            except Exception:
                pass

        display_title = meta.title or f"{meta.series} #{meta.number}".strip()
        if existing is None:
            item = Item(
                library_id=library.id,
                kind=ItemKind.COMIC.value,
                rel_path=rel_path,
                title=display_title,
                year=meta.year,
                state=state,
                provider_ids_json=json.dumps(provider_ids),
                metadata_json=meta.model_dump_json(),
                sidecar_mtime=xml_mtime,
                media_mtime=stat.st_mtime,
                media_size=stat.st_size,
                scanned_at=now,
            )
            session.add(item)
            await session.flush()
            stats.added += 1
        else:
            item = existing
            if existing.state != ItemState.DIRTY.value:
                existing.title = display_title
                existing.year = meta.year
                existing.metadata_json = meta.model_dump_json()
                existing.state = state
            existing.sidecar_mtime = xml_mtime
            existing.media_mtime = stat.st_mtime
            existing.media_size = stat.st_size
            existing.scanned_at = now
            stats.updated += 1

        cover_path = cbz_path.with_suffix(".jpg")
        if cover_path.is_file():
            art_rel = cover_path.relative_to(root).as_posix()
            existing_art = (
                await session.execute(
                    select(Artwork).where(
                        Artwork.item_id == item.id,
                        Artwork.type == ArtworkType.COVER.value,
                    )
                )
            ).scalar_one_or_none()
            if existing_art is None:
                session.add(
                    Artwork(
                        item_id=item.id,
                        type=ArtworkType.COVER.value,
                        rel_path=art_rel,
                    )
                )
            else:
                existing_art.rel_path = art_rel

            if sidecar_xml.is_file() and item.state == ItemState.MATCHED.value:
                item.state = ItemState.COMPLETE.value

    await session.commit()
    return stats
