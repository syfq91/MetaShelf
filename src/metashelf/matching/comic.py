"""Comic series-to-volume and issue auto-matching via Comic Vine."""

import json
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, ComicMetadata, ItemKind, ItemState
from metashelf.providers.base import SearchQuery
from metashelf.providers.comicvine import ComicVineProvider, VolumeIssueSummary
from metashelf.readers.comicinfo_xml import read_comicinfo_file
from metashelf.services.paths import resolve_within_root
from metashelf.writers.artwork import ArtworkDownloadError, DownloadedArtwork, download_artwork
from metashelf.writers.comic_cover import extract_cbz_first_page_cover
from metashelf.writers.comicinfo_xml import write_comicinfo_xml


def _normalize_issue_key(raw: str) -> str:
    s = raw.strip().lstrip("#")
    if s.isdigit():
        return str(int(s))
    return s.lower()


async def auto_match_comic_library(
    session: AsyncSession,
    library: Library,
    cv: ComicVineProvider,
    http_client: httpx.AsyncClient,
    cover_source: str = "provider",
) -> int:
    """Auto-match unmatched CBZ comics by series volume and issue number."""
    root = Path(library.root_path).resolve()
    items = (
        await session.execute(
            select(Item)
            .where(
                Item.library_id == library.id,
                Item.kind == ItemKind.COMIC.value,
                Item.state == ItemState.UNMATCHED.value,
            )
            .order_by(Item.rel_path)
        )
    ).scalars().all()

    # Group items by series to avoid redundant volume searches
    by_series: dict[str, list[Item]] = {}
    for item in items:
        pids: dict[str, str] = json.loads(item.provider_ids_json or "{}")
        if pids or item.state == ItemState.DIRTY.value:
            continue
        meta = ComicMetadata.model_validate_json(item.metadata_json or "{}")
        key = meta.series or Path(item.rel_path).parts[0]
        by_series.setdefault(key, []).append(item)

    matched_count = 0
    for series_name, series_items in by_series.items():
        vols = await cv.search("comic", SearchQuery(title=series_name))
        if not vols:
            continue
        best_vol = vols[0]
        publisher = best_vol.extra.get("publisher", "")
        issues = await cv.list_volume_issues(best_vol.provider_id)
        by_num: dict[str, VolumeIssueSummary] = {
            _normalize_issue_key(iss.number): iss for iss in issues if iss.number
        }

        for item in series_items:
            local_meta = ComicMetadata.model_validate_json(item.metadata_json or "{}")
            iss_summary = by_num.get(_normalize_issue_key(local_meta.number))
            if iss_summary is None:
                continue

            fetched = await cv.fetch("comic", iss_summary.issue_id, "en")
            assert isinstance(fetched, ComicMetadata)
            if not fetched.publisher and publisher:
                fetched.publisher = publisher
            if fetched.volume is None and local_meta.volume is not None:
                fetched.volume = local_meta.volume

            cbz_path = resolve_within_root(item.rel_path, root)
            xml_path = cbz_path.with_suffix(".xml")
            unknown = None
            if xml_path.is_file():
                try:
                    unknown = read_comicinfo_file(xml_path).unknown_elements
                except Exception:
                    unknown = None

            write_comicinfo_xml(xml_path, fetched, unknown_elements=unknown)

            item.title = fetched.title or f"{fetched.series} #{fetched.number}".strip()
            item.year = fetched.year
            item.provider_ids_json = json.dumps(
                {
                    "comicvine_volume": best_vol.provider_id,
                    "comicvine_issue": iss_summary.issue_id,
                }
            )
            item.metadata_json = fetched.model_dump_json()
            item.sidecar_mtime = xml_path.stat().st_mtime

            cover_target = cbz_path.with_suffix(".jpg")
            dl: DownloadedArtwork | None = None
            source_url: str | None = None
            if cover_source == "archive":
                dl = extract_cbz_first_page_cover(cbz_path, cover_target)
            else:
                arts = await cv.artwork("comic", iss_summary.issue_id)
                if arts:
                    try:
                        dl = await download_artwork(http_client, arts[0].url, cover_target)
                        source_url = arts[0].url
                    except ArtworkDownloadError:
                        dl = None
                if dl is None:
                    dl = extract_cbz_first_page_cover(cbz_path, cover_target)

            if dl is not None:
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
                            source_url=source_url,
                            width=dl.width,
                            height=dl.height,
                        )
                    )
                else:
                    existing_art.rel_path = rel_cover
                    existing_art.source_url = source_url
                    existing_art.width = dl.width
                    existing_art.height = dl.height

            item.state = ItemState.COMPLETE.value if dl is not None else ItemState.MATCHED.value
            matched_count += 1

    await session.commit()
    return matched_count
