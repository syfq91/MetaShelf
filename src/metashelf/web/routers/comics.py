"""Comics library view (series-grouped list), detail editor, and ComicInfo.xml saving."""

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.auth.deps import CurrentUser, DbSession, require_csrf
from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, ComicMetadata, ItemKind, ItemState
from metashelf.providers.base import ProviderError, SearchQuery
from metashelf.readers.comicinfo_xml import read_comicinfo_file
from metashelf.services.googlebooks_scrape import (
    get_google_books_provider,
    save_googlebooks_cover,
)
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


@router.get("/{item_id}/scrape", response_class=HTMLResponse)
async def comic_scrape_modal(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    """Open Google Books search modal prefilled from comic metadata."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.COMIC.value:
        raise HTTPException(status_code=404, detail="Comic not found")
    meta = ComicMetadata.model_validate_json(item.metadata_json or "{}")
    base = request.app.state.settings.base_url.rstrip("/")
    return render_template(
        request,
        "partials/_googlebooks_modal.html",
        {
            "modal_title": "Search Google Books (Comic)",
            "search_url": f"{base}/comics/{item.id}/scrape/search",
            "apply_url": f"{base}/comics/{item.id}/scrape/apply",
            "target_pane": "#comic-detail-pane",
            "show_isbn": False,
            "query_title": meta.series or meta.title or item.title,
            "query_author": meta.writers[0] if meta.writers else "",
            "query_isbn": "",
            "candidates": None,
            "error": None,
        },
    )


@router.post(
    "/{item_id}/scrape/search",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def comic_scrape_search(
    request: Request,
    session: DbSession,
    item_id: int,
    title: Annotated[str, Form()],
    author: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Search Google Books for comic candidates."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.COMIC.value:
        raise HTTPException(status_code=404, detail="Comic not found")

    provider = get_google_books_provider(request, session)
    candidates = []
    error: str | None = None
    try:
        candidates = await provider.search(
            "comic",
            SearchQuery(title=title.strip(), author=author.strip()),
        )
        await session.commit()
    except ProviderError as exc:
        error = str(exc)

    base = request.app.state.settings.base_url.rstrip("/")
    return render_template(
        request,
        "partials/_googlebooks_modal.html",
        {
            "modal_title": "Search Google Books (Comic)",
            "search_url": f"{base}/comics/{item.id}/scrape/search",
            "apply_url": f"{base}/comics/{item.id}/scrape/apply",
            "target_pane": "#comic-detail-pane",
            "show_isbn": False,
            "query_title": title.strip(),
            "query_author": author.strip(),
            "query_isbn": "",
            "candidates": candidates,
            "error": error,
        },
    )


@router.post(
    "/{item_id}/scrape/apply",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def comic_scrape_apply(
    request: Request,
    session: DbSession,
    item_id: int,
    provider_id: Annotated[str, Form()],
) -> HTMLResponse:
    """Fetch comic metadata and cover from Google Books and stage on item."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.COMIC.value:
        raise HTTPException(status_code=404, detail="Comic not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    local_meta = ComicMetadata.model_validate_json(item.metadata_json or "{}")
    provider = get_google_books_provider(request, session)
    fetched = await provider.fetch("comic", provider_id)
    assert isinstance(fetched, ComicMetadata)

    if not fetched.number and local_meta.number:
        fetched.number = local_meta.number
    if fetched.volume is None and local_meta.volume is not None:
        fetched.volume = local_meta.volume
    if not fetched.artists and local_meta.artists:
        fetched.artists = local_meta.artists
    if not fetched.title:
        fetched.title = local_meta.title or item.title

    root = Path(library.root_path).resolve()
    cbz_path = resolve_within_root(item.rel_path, root)
    cover_path = cbz_path.with_suffix(".jpg")
    await save_googlebooks_cover(
        session,
        request.app.state.http_client,
        provider,
        item,
        "comic",
        provider_id,
        cover_path,
        root,
    )

    pids: dict[str, str] = json.loads(item.provider_ids_json or "{}")
    pids["googlebooks"] = provider_id
    item.title = fetched.title
    item.year = fetched.year
    item.provider_ids_json = json.dumps(pids)
    item.metadata_json = fetched.model_dump_json()
    item.state = ItemState.DIRTY.value
    await session.commit()

    ctx = await _comic_detail_context(
        session,
        item,
        toast="Applied Google Books metadata. Click Save ComicInfo XML to write.",
    )
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
