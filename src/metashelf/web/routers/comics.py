"""Comics library view (series-grouped list), detail editor, and ComicInfo.xml saving."""

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.auth.deps import CurrentUser, DbSession, require_csrf
from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, ComicMetadata, ItemKind, ItemState
from metashelf.readers.comicinfo_xml import read_comicinfo_file
from metashelf.services.paths import PathTraversalError, resolve_within_root
from metashelf.web.templating import get_nav_context, render_template
from metashelf.writers.comicinfo_xml import write_comicinfo_xml

router = APIRouter(prefix="/comics", tags=["comics"])


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


async def _comic_detail_context(
    session: AsyncSession,
    item: Item,
    toast: str | None = None,
) -> dict[str, Any]:
    arts = (
        await session.execute(select(Artwork).where(Artwork.item_id == item.id))
    ).scalars().all()
    art_map = {a.type: a for a in arts}
    meta = ComicMetadata.model_validate_json(item.metadata_json or "{}")
    return {
        "item": item,
        "meta": meta,
        "art_map": art_map,
        "toast": toast,
    }


def _group_by_series(items: list[Item]) -> list[tuple[str, list[tuple[Item, ComicMetadata]]]]:
    groups: dict[str, list[tuple[Item, ComicMetadata]]] = {}
    for item in items:
        meta = ComicMetadata.model_validate_json(item.metadata_json or "{}")
        series_name = meta.series or "Ungrouped"
        groups.setdefault(series_name, []).append((item, meta))
    return sorted(groups.items(), key=lambda pair: pair[0].lower())


@router.get("", response_class=HTMLResponse)
async def comics_index(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    q: Annotated[str, Query()] = "",
    selected_id: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render two-pane Comics library view grouped by series -> issue."""
    nav_ctx = await get_nav_context(session)
    stmt = select(Item).where(Item.kind == ItemKind.COMIC.value)
    if q.strip():
        stmt = stmt.where(Item.title.ilike(f"%{q.strip()}%"))
    items = list((await session.execute(stmt.order_by(Item.rel_path.asc()))).scalars().all())
    series_groups = _group_by_series(items)

    selected_item: Item | None = None
    if selected_id is not None:
        selected_item = await session.get(Item, selected_id)
    elif items:
        selected_item = items[0]

    detail_ctx = await _comic_detail_context(session, selected_item) if selected_item else {}
    return render_template(
        request,
        "comics/index.html",
        {
            "active_nav": "comics",
            "q": q,
            "series_groups": series_groups,
            "selected_item": selected_item,
            **nav_ctx,
            **detail_ctx,
        },
    )


@router.get("/{item_id}", response_class=HTMLResponse)
async def comic_detail_fragment(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.COMIC.value:
        raise HTTPException(status_code=404, detail="Comic not found")
    ctx = await _comic_detail_context(session, item)
    return render_template(request, "comics/_detail.html", ctx)


@router.post(
    "/{item_id}/edit",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def comic_edit(
    request: Request,
    session: DbSession,
    item_id: int,
    title: Annotated[str, Form()] = "",
    series: Annotated[str, Form()] = "",
    number: Annotated[str, Form()] = "",
    volume: Annotated[str, Form()] = "",
    year: Annotated[str, Form()] = "",
    publisher: Annotated[str, Form()] = "",
    writers: Annotated[str, Form()] = "",
    artists: Annotated[str, Form()] = "",
    summary: Annotated[str, Form()] = "",
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.COMIC.value:
        raise HTTPException(status_code=404, detail="Comic not found")

    meta = ComicMetadata.model_validate_json(item.metadata_json or "{}")
    meta.title = title.strip()
    meta.series = series.strip()
    meta.number = number.strip()
    meta.volume = int(volume.strip()) if volume.strip().isdigit() else None
    meta.year = int(year.strip()) if year.strip().isdigit() else None
    meta.publisher = publisher.strip()
    meta.writers = _split_csv(writers)
    meta.artists = _split_csv(artists)
    meta.pencillers = meta.artists
    meta.summary = summary.strip()

    item.title = meta.title or f"{meta.series} #{meta.number}".strip()
    item.year = meta.year
    item.metadata_json = meta.model_dump_json()
    item.state = ItemState.DIRTY.value
    await session.commit()

    ctx = await _comic_detail_context(session, item, toast="Changes staged (dirty).")
    return render_template(request, "comics/_detail.html", ctx)


@router.post(
    "/{item_id}/save",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def comic_save(
    request: Request,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.COMIC.value:
        raise HTTPException(status_code=404, detail="Comic not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    root = Path(library.root_path).resolve()
    cbz_path = resolve_within_root(item.rel_path, root)
    xml_path = cbz_path.with_suffix(".xml")

    unknown = None
    if xml_path.is_file():
        try:
            unknown = read_comicinfo_file(xml_path).unknown_elements
        except Exception:
            unknown = None

    meta = ComicMetadata.model_validate_json(item.metadata_json or "{}")
    write_comicinfo_xml(xml_path, meta, unknown_elements=unknown)
    item.sidecar_mtime = xml_path.stat().st_mtime
    has_cover = (
        await session.execute(
            select(Artwork).where(
                Artwork.item_id == item.id,
                Artwork.type == ArtworkType.COVER.value,
            )
        )
    ).scalar_one_or_none() is not None
    item.state = ItemState.COMPLETE.value if has_cover else ItemState.MATCHED.value
    await session.commit()

    ctx = await _comic_detail_context(session, item, toast="Saved ComicInfo XML sidecar to disk.")
    return render_template(request, "comics/_detail.html", ctx)


@router.get("/{item_id}/artwork/{art_type}")
async def serve_comic_artwork(
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
    art_type: str,
) -> FileResponse:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")
    art = (
        await session.execute(
            select(Artwork).where(Artwork.item_id == item.id, Artwork.type == art_type)
        )
    ).scalar_one_or_none()
    if art is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        file_path = resolve_within_root(art.rel_path, Path(library.root_path))
    except PathTraversalError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Artwork missing")
    return FileResponse(file_path)
