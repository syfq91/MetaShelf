"""Ebook (.epub) library scanner with embedded OPF prefill and sidecar adoption."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, EbookMetadata, ItemKind, ItemState
from metashelf.readers.opf_ebook import read_epub_embedded_opf, read_opf_file
from metashelf.scanner.movie import ScanStats


async def scan_ebook_library(session: AsyncSession, library: Library) -> ScanStats:
    """Scan an ebook library root for .epub files incrementally."""
    root = Path(library.root_path).resolve()
    stats = ScanStats()
    if not root.exists() or not root.is_dir():
        return stats

    existing_rows = (
        await session.execute(select(Item).where(Item.library_id == library.id))
    ).scalars().all()
    by_rel_path: dict[str, Item] = {item.rel_path: item for item in existing_rows}

    epub_files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() == ".epub" and not p.name.startswith(".")
    )
    now = datetime.now(UTC)

    for epub_path in epub_files:
        rel_path = epub_path.relative_to(root).as_posix()
        stat = epub_path.stat()
        sidecar_opf = epub_path.with_suffix(".opf")
        opf_mtime = sidecar_opf.stat().st_mtime if sidecar_opf.is_file() else None

        existing = by_rel_path.get(rel_path)
        if (
            existing is not None
            and existing.media_mtime == stat.st_mtime
            and existing.media_size == stat.st_size
            and existing.sidecar_mtime == opf_mtime
        ):
            stats.skipped += 1
            continue

        meta = EbookMetadata(title=epub_path.stem)
        provider_ids: dict[str, str] = {}
        state = ItemState.UNMATCHED.value

        # Sidecar .opf wins when present; otherwise read embedded OPF inside the EPUB
        if sidecar_opf.is_file():
            try:
                meta = read_opf_file(sidecar_opf).metadata
                if meta.openlibrary_id:
                    provider_ids["openlibrary"] = meta.openlibrary_id
                if meta.googlebooks_id:
                    provider_ids["googlebooks"] = meta.googlebooks_id
                if provider_ids or meta.isbn or meta.description:
                    state = ItemState.MATCHED.value
            except Exception:
                state = ItemState.ERROR.value
        else:
            try:
                embedded = read_epub_embedded_opf(epub_path)
                if embedded is not None:
                    meta = embedded.metadata
                    if not meta.title:
                        meta.title = epub_path.stem
            except Exception:
                pass

        if existing is None:
            item = Item(
                library_id=library.id,
                kind=ItemKind.EBOOK.value,
                rel_path=rel_path,
                title=meta.title or epub_path.stem,
                year=meta.year,
                state=state,
                provider_ids_json=json.dumps(provider_ids),
                metadata_json=meta.model_dump_json(),
                sidecar_mtime=opf_mtime,
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
                existing.title = meta.title or epub_path.stem
                existing.year = meta.year
                existing.metadata_json = meta.model_dump_json()
                if provider_ids:
                    existing.provider_ids_json = json.dumps(provider_ids)
                    existing.state = state
            existing.sidecar_mtime = opf_mtime
            existing.media_mtime = stat.st_mtime
            existing.media_size = stat.st_size
            existing.scanned_at = now
            stats.updated += 1

        cover_path = epub_path.with_suffix(".jpg")
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

            if sidecar_opf.is_file() and item.state == ItemState.MATCHED.value:
                item.state = ItemState.COMPLETE.value

    await session.commit()
    return stats
