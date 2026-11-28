"""Ebooks library view, detail editor (series, multiple authors, ISBN), and OPF saving."""

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.auth.deps import CurrentUser, DbSession, require_csrf
from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, EbookMetadata, ItemKind, ItemState
from metashelf.providers.base import ProviderError, SearchQuery
from metashelf.readers.opf_ebook import read_opf_file
from metashelf.services.googlebooks_scrape import (
    get_google_books_provider,
    save_googlebooks_cover,
)
from metashelf.services.paths import PathTraversalError, resolve_within_root
from metashelf.web.templating import get_nav_context, render_template
from metashelf.writers.opf_ebook import write_opf

router = APIRouter(prefix="/ebooks", tags=["ebooks"])


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


async def _ebook_detail_context(
    session: AsyncSession,
    item: Item,
    toast: str | None = None,
) -> dict[str, Any]:
    arts = (
        await session.execute(select(Artwork).where(Artwork.item_id == item.id))
    ).scalars().all()
    art_map = {a.type: a for a in arts}
    meta = EbookMetadata.model_validate_json(item.metadata_json or "{}")
    return {
        "item": item,
        "meta": meta,
        "art_map": art_map,
        "toast": toast,
    }


@router.get("", response_class=HTMLResponse)
async def ebooks_index(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    q: Annotated[str, Query()] = "",
    selected_id: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render two-pane Ebooks library view."""
    nav_ctx = await get_nav_context(session)
    stmt = select(Item).where(Item.kind == ItemKind.EBOOK.value)
    if q.strip():
        stmt = stmt.where(Item.title.ilike(f"%{q.strip()}%"))
    items = list((await session.execute(stmt.order_by(Item.title.asc()))).scalars().all())

    selected_item: Item | None = None
    if selected_id is not None:
        selected_item = await session.get(Item, selected_id)
    elif items:
        selected_item = items[0]

    detail_ctx = await _ebook_detail_context(session, selected_item) if selected_item else {}
    return render_template(
        request,
        "ebooks/index.html",
        {
            "active_nav": "ebooks",
            "q": q,
            "items": items,
            "selected_item": selected_item,
            **nav_ctx,
            **detail_ctx,
        },
    )


@router.get("/{item_id}", response_class=HTMLResponse)
async def ebook_detail_fragment(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.EBOOK.value:
        raise HTTPException(status_code=404, detail="Ebook not found")
    ctx = await _ebook_detail_context(session, item)
    return render_template(request, "ebooks/_detail.html", ctx)


@router.post(
    "/{item_id}/edit",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def ebook_edit(
    request: Request,
    session: DbSession,
    item_id: int,
    title: Annotated[str, Form()] = "",
    authors: Annotated[str, Form()] = "",
    isbn: Annotated[str, Form()] = "",
    series: Annotated[str, Form()] = "",
    series_index: Annotated[str, Form()] = "",
    publisher: Annotated[str, Form()] = "",
    published_date: Annotated[str, Form()] = "",
    subjects: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.EBOOK.value:
        raise HTTPException(status_code=404, detail="Ebook not found")

    meta = EbookMetadata.model_validate_json(item.metadata_json or "{}")
    meta.title = title.strip()
    meta.authors = _split_csv(authors)
    meta.isbn = isbn.strip()
    meta.series = series.strip()
    meta.series_index = series_index.strip()
    meta.publisher = publisher.strip()
    meta.published_date = published_date.strip()
    if meta.published_date and len(meta.published_date) >= 4 and meta.published_date[:4].isdigit():
        meta.year = int(meta.published_date[:4])
    meta.subjects = _split_csv(subjects)
    meta.description = description.strip()

    item.title = meta.title or item.title
    item.year = meta.year
    item.metadata_json = meta.model_dump_json()
    item.state = ItemState.DIRTY.value
    await session.commit()

    ctx = await _ebook_detail_context(session, item, toast="Changes staged (dirty).")
    return render_template(request, "ebooks/_detail.html", ctx)


@router.post(
    "/{item_id}/save",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def ebook_save(
    request: Request,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.EBOOK.value:
        raise HTTPException(status_code=404, detail="Ebook not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    root = Path(library.root_path).resolve()
    epub_path = resolve_within_root(item.rel_path, root)
    opf_path = epub_path.with_suffix(".opf")

    unknown = None
    if opf_path.is_file():
        try:
            unknown = read_opf_file(opf_path).unknown_elements
        except Exception:
            unknown = None

    meta = EbookMetadata.model_validate_json(item.metadata_json or "{}")
    write_opf(opf_path, meta, unknown_elements=unknown)
    item.sidecar_mtime = opf_path.stat().st_mtime
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

    ctx = await _ebook_detail_context(session, item, toast="Saved .opf sidecar to disk.")
    return render_template(request, "ebooks/_detail.html", ctx)


@router.get("/{item_id}/scrape", response_class=HTMLResponse)
async def ebook_scrape_modal(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    """Open Google Books search modal prefilled from ebook metadata."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.EBOOK.value:
        raise HTTPException(status_code=404, detail="Ebook not found")
    meta = EbookMetadata.model_validate_json(item.metadata_json or "{}")
    base = request.app.state.settings.base_url.rstrip("/")
    return render_template(
        request,
        "partials/_googlebooks_modal.html",
        {
            "modal_title": "Search Google Books (Ebook)",
            "search_url": f"{base}/ebooks/{item.id}/scrape/search",
            "apply_url": f"{base}/ebooks/{item.id}/scrape/apply",
            "target_pane": "#ebook-detail-pane",
            "show_isbn": True,
            "query_title": meta.title or item.title,
            "query_author": meta.authors[0] if meta.authors else "",
            "query_isbn": meta.isbn,
            "candidates": None,
            "error": None,
        },
    )


@router.post(
    "/{item_id}/scrape/search",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def ebook_scrape_search(
    request: Request,
    session: DbSession,
    item_id: int,
    title: Annotated[str, Form()],
    author: Annotated[str, Form()] = "",
    isbn: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Search Google Books for ebook candidates."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.EBOOK.value:
        raise HTTPException(status_code=404, detail="Ebook not found")

    provider = get_google_books_provider(request, session)
    candidates = []
    error: str | None = None
    try:
        candidates = await provider.search(
            "ebook",
            SearchQuery(title=title.strip(), author=author.strip(), isbn=isbn.strip()),
        )
        await session.commit()
    except ProviderError as exc:
        error = str(exc)

    base = request.app.state.settings.base_url.rstrip("/")
    return render_template(
        request,
        "partials/_googlebooks_modal.html",
        {
            "modal_title": "Search Google Books (Ebook)",
            "search_url": f"{base}/ebooks/{item.id}/scrape/search",
            "apply_url": f"{base}/ebooks/{item.id}/scrape/apply",
            "target_pane": "#ebook-detail-pane",
            "show_isbn": True,
            "query_title": title.strip(),
            "query_author": author.strip(),
            "query_isbn": isbn.strip(),
            "candidates": candidates,
            "error": error,
        },
    )


@router.post(
    "/{item_id}/scrape/apply",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def ebook_scrape_apply(
    request: Request,
    session: DbSession,
    item_id: int,
    provider_id: Annotated[str, Form()],
) -> HTMLResponse:
    """Fetch ebook metadata and cover from Google Books and stage on item."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.EBOOK.value:
        raise HTTPException(status_code=404, detail="Ebook not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    local_meta = EbookMetadata.model_validate_json(item.metadata_json or "{}")
    provider = get_google_books_provider(request, session)
    fetched = await provider.fetch("ebook", provider_id, local_meta.language or "en")
    assert isinstance(fetched, EbookMetadata)

    if not fetched.authors and local_meta.authors:
        fetched.authors = local_meta.authors
    if not fetched.series and local_meta.series:
        fetched.series = local_meta.series
        fetched.series_index = local_meta.series_index
    if not fetched.isbn and local_meta.isbn:
        fetched.isbn = local_meta.isbn
    if not fetched.title:
        fetched.title = local_meta.title or item.title

    root = Path(library.root_path).resolve()
    epub_path = resolve_within_root(item.rel_path, root)
    cover_path = epub_path.parent / "cover.jpg"
    await save_googlebooks_cover(
        session,
        request.app.state.http_client,
        provider,
        item,
        "ebook",
        provider_id,
        cover_path,
        root,
    )

    pids: dict[str, str] = json.loads(item.provider_ids_json or "{}")
    pids["googlebooks"] = fetched.googlebooks_id or provider_id
    item.title = fetched.title
    item.year = fetched.year
    item.provider_ids_json = json.dumps(pids)
    item.metadata_json = fetched.model_dump_json()
    item.state = ItemState.DIRTY.value
    await session.commit()

    ctx = await _ebook_detail_context(
        session,
        item,
        toast="Applied Google Books metadata. Click Save .opf to write.",
    )
    return render_template(request, "ebooks/_detail.html", ctx)


@router.get("/{item_id}/artwork/{art_type}")
async def serve_ebook_artwork(
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
