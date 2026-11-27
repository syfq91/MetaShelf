"""Ebook ISBN-first matching and sidecar writing."""

import json
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, EbookMetadata, ItemKind, ItemState
from metashelf.providers.base import SearchQuery
from metashelf.providers.googlebooks import GoogleBooksProvider
from metashelf.providers.openlibrary import OpenLibraryProvider
from metashelf.readers.opf_ebook import read_opf_file
from metashelf.services.paths import resolve_within_root
from metashelf.writers.artwork import ArtworkDownloadError, download_artwork
from metashelf.writers.opf_ebook import write_opf


async def auto_match_ebook_library(
    session: AsyncSession,
    library: Library,
    ol: OpenLibraryProvider,
    gb: GoogleBooksProvider | None,
    http_client: httpx.AsyncClient,
) -> int:
    """Auto-match unmatched ebooks using ISBN-first search, then title+author."""
    root = Path(library.root_path).resolve()
    items = (
        await session.execute(
            select(Item).where(
                Item.library_id == library.id,
                Item.kind == ItemKind.EBOOK.value,
                Item.state == ItemState.UNMATCHED.value,
            )
        )
    ).scalars().all()

    matched_count = 0
    for item in items:
        pids: dict[str, str] = json.loads(item.provider_ids_json or "{}")
        if pids or item.state == ItemState.DIRTY.value:
            continue

        local_meta = EbookMetadata.model_validate_json(item.metadata_json or "{}")
        query = SearchQuery(
            title=local_meta.title or item.title,
            author=local_meta.authors[0] if local_meta.authors else None,
            isbn=local_meta.isbn or None,
        )

        fetched: EbookMetadata | None = None
        art_url: str | None = None

        ol_cands = await ol.search("ebook", query)
        if ol_cands:
            best = ol_cands[0]
            raw = await ol.fetch("ebook", best.provider_id, local_meta.language or "en")
            assert isinstance(raw, EbookMetadata)
            fetched = raw
            pids["openlibrary"] = raw.openlibrary_id or best.provider_id
            arts = await ol.artwork("ebook", best.provider_id)
            if arts:
                art_url = arts[0].url
        elif gb is not None:
            gb_cands = await gb.search("ebook", query)
            if gb_cands:
                best = gb_cands[0]
                raw = await gb.fetch("ebook", best.provider_id, local_meta.language or "en")
                assert isinstance(raw, EbookMetadata)
                fetched = raw
                pids["googlebooks"] = raw.googlebooks_id or best.provider_id
                arts = await gb.artwork("ebook", best.provider_id)
                if arts:
                    art_url = arts[0].url

        if fetched is None:
            continue

        # Merge: preserve embedded authors/series/isbn if provider returned empty
        if not fetched.authors and local_meta.authors:
            fetched.authors = local_meta.authors
        if not fetched.series and local_meta.series:
            fetched.series = local_meta.series
            fetched.series_index = local_meta.series_index
        if not fetched.isbn and local_meta.isbn:
            fetched.isbn = local_meta.isbn
        if not fetched.title:
            fetched.title = local_meta.title or item.title

        epub_path = resolve_within_root(item.rel_path, root)
        opf_path = epub_path.with_suffix(".opf")
        unknown = None
        if opf_path.is_file():
            try:
                unknown = read_opf_file(opf_path).unknown_elements
            except Exception:
                unknown = None

        write_opf(opf_path, fetched, unknown_elements=unknown)

        item.title = fetched.title
        item.year = fetched.year
        item.provider_ids_json = json.dumps(pids)
        item.metadata_json = fetched.model_dump_json()
        item.sidecar_mtime = opf_path.stat().st_mtime

        has_cover = False
        if art_url:
            cover_target = epub_path.with_suffix(".jpg")
            try:
                dl = await download_artwork(
                    http_client, art_url, cover_target, allow_redirects=True
                )
                rel_cover = dl.path.relative_to(root).as_posix()
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
                            rel_path=rel_cover,
                            source_url=art_url,
                            width=dl.width,
                            height=dl.height,
                        )
                    )
                else:
                    existing_art.rel_path = rel_cover
                    existing_art.source_url = art_url
                    existing_art.width = dl.width
                    existing_art.height = dl.height
                has_cover = True
            except ArtworkDownloadError:
                pass

        item.state = ItemState.COMPLETE.value if has_cover else ItemState.MATCHED.value
        matched_count += 1

    await session.commit()
    return matched_count
