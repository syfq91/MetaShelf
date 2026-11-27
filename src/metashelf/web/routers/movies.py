"""Movies library view, detail editor, artwork serving, and scrape modal routes."""

import json
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.auth.deps import CurrentUser, DbSession, require_csrf
from metashelf.db.models import Artwork, Item, Library, SidecarFile
from metashelf.domain.models import ArtworkType, ItemKind, ItemState, MovieMetadata
from metashelf.providers.base import (
    MissingApiKeyError,
    ProviderError,
    QuotaExceededError,
    SearchQuery,
    SubtitleCandidate,
    SubtitleQuery,
)
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.opensubtitles import OpenSubtitlesProvider, compute_opensubtitles_hash
from metashelf.providers.tmdb import TMDBProvider
from metashelf.scanner.movie import find_movie_nfo
from metashelf.scanner.parser import parse_movie_filename
from metashelf.services.batch import execute_batch_action
from metashelf.services.movie_save import (
    resolve_movie_artwork_target,
    revert_movie_from_disk,
    save_movie_to_disk,
)
from metashelf.services.paths import PathTraversalError, resolve_within_root
from metashelf.web.routers.settings import (
    SETTING_LANGUAGE,
    SETTING_MOVIE_NAMING,
    SETTING_TMDB_KEY,
    get_setting_value,
)
from metashelf.web.templating import get_nav_context, render_template
from metashelf.writers.artwork import ArtworkDownloadError, download_artwork
from metashelf.writers.subtitles import (
    SubtitleExistsError,
    find_existing_subtitles,
    write_subtitle_file,
)

router = APIRouter(prefix="/movies", tags=["movies"])

PAGE_SIZE = 50


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _build_movie_query(
    q: str = "",
    flt: str = "all",
    sort: str = "title",
) -> Select[Item]:
    stmt = select(Item).where(Item.kind == ItemKind.MOVIE.value)
    if q.strip():
        stmt = stmt.where(Item.title.ilike(f"%{q.strip()}%"))
    if flt == "unmatched":
        stmt = stmt.where(Item.state == ItemState.UNMATCHED.value)
    elif flt == "dirty":
        stmt = stmt.where(Item.state == ItemState.DIRTY.value)
    elif flt == "missing_artwork":
        has_poster = select(Artwork.id).where(
            Artwork.item_id == Item.id,
            Artwork.type == ArtworkType.POSTER.value,
        )
        stmt = stmt.where(~has_poster.exists())

    if sort == "year":
        stmt = stmt.order_by(Item.year.desc().nullslast(), Item.title.asc())
    else:
        stmt = stmt.order_by(Item.title.asc(), Item.id.asc())
    return stmt


async def _load_artwork_map(
    session: AsyncSession,
    item_ids: list[int],
) -> dict[int, dict[str, Artwork]]:
    if not item_ids:
        return {}
    rows = (
        await session.execute(select(Artwork).where(Artwork.item_id.in_(item_ids)))
    ).scalars().all()
    result: dict[int, dict[str, Artwork]] = {}
    for art in rows:
        result.setdefault(art.item_id, {})[art.type] = art
    return result


async def _detail_context(
    session: AsyncSession,
    item: Item,
    tab: str = "info",
    toast: str | None = None,
) -> dict[str, Any]:
    library = await session.get(Library, item.library_id)
    artworks = (
        await session.execute(select(Artwork).where(Artwork.item_id == item.id))
    ).scalars().all()
    art_map = {a.type: a for a in artworks}
    meta = MovieMetadata.model_validate_json(item.metadata_json or "{}")
    parsed = parse_movie_filename(item.rel_path)

    nfo_exists = False
    nfo_rel = ""
    subtitles_on_disk: list[Path] = []
    if library is not None:
        root = Path(library.root_path).resolve()
        video_path = resolve_within_root(item.rel_path, root)
        nfo_path = find_movie_nfo(video_path)
        if nfo_path is not None:
            nfo_exists = True
            nfo_rel = nfo_path.relative_to(root).as_posix()
        subtitles_on_disk = find_existing_subtitles(video_path)

    return {
        "item": item,
        "library": library,
        "meta": meta,
        "art_map": art_map,
        "parsed": parsed,
        "nfo_exists": nfo_exists,
        "nfo_rel": nfo_rel,
        "subtitles_on_disk": subtitles_on_disk,
        "tab": tab,
        "toast": toast,
    }


@router.get("", response_class=HTMLResponse)
async def movies_index(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    q: Annotated[str, Query()] = "",
    flt: Annotated[str, Query()] = "all",
    sort: Annotated[str, Query()] = "title",
    selected_id: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render the two-pane Movies library view."""
    nav_ctx = await get_nav_context(session)
    stmt = _build_movie_query(q=q, flt=flt, sort=sort).limit(PAGE_SIZE)
    items = list((await session.execute(stmt)).scalars().all())
    art_by_item = await _load_artwork_map(session, [i.id for i in items])

    selected_item: Item | None = None
    if selected_id is not None:
        selected_item = await session.get(Item, selected_id)
    elif items:
        selected_item = items[0]

    detail_ctx = await _detail_context(session, selected_item) if selected_item else {}
    return render_template(
        request,
        "movies/index.html",
        {
            "active_nav": "movies",
            "global_query": q,
            "q": q,
            "flt": flt,
            "sort": sort,
            "items": items,
            "art_by_item": art_by_item,
            "page": 1,
            "has_more": len(items) == PAGE_SIZE,
            "selected_item": selected_item,
            **nav_ctx,
            **detail_ctx,
        },
    )


@router.post("/batch", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
async def movies_batch_action(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_ids: Annotated[list[int] | None, Form()] = None,
    action: Annotated[str, Form()] = "save",
    dry_run: Annotated[str, Form()] = "true",
) -> HTMLResponse:
    """Preview or execute a batch action over selected movie items."""
    is_dry_run = dry_run.lower() in {"true", "1", "yes", "on"}
    naming_scheme = await get_setting_value(session, SETTING_MOVIE_NAMING, "file")
    tmdb_key = await get_setting_value(session, SETTING_TMDB_KEY, "")
    lang = await get_setting_value(session, SETTING_LANGUAGE, "en-US")
    result = await execute_batch_action(
        session,
        item_ids=item_ids or [],
        action=action,
        dry_run=is_dry_run,
        naming_scheme=naming_scheme,
        tmdb_api_key=tmdb_key,
        lang=lang,
    )
    return render_template(
        request,
        "movies/_batch_preview.html",
        {"result": result},
    )


@router.get("/list", response_class=HTMLResponse)
async def movies_list_fragment(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    q: Annotated[str, Query()] = "",
    flt: Annotated[str, Query()] = "all",
    sort: Annotated[str, Query()] = "title",
    page: Annotated[int, Query(ge=1)] = 1,
    selected_id: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Return HTMX fragment for the left movie list pane."""
    offset = (page - 1) * PAGE_SIZE
    stmt = _build_movie_query(q=q, flt=flt, sort=sort).offset(offset).limit(PAGE_SIZE)
    items = list((await session.execute(stmt)).scalars().all())
    art_by_item = await _load_artwork_map(session, [i.id for i in items])
    return render_template(
        request,
        "movies/_list.html",
        {
            "items": items,
            "art_by_item": art_by_item,
            "q": q,
            "flt": flt,
            "sort": sort,
            "page": page,
            "has_more": len(items) == PAGE_SIZE,
            "selected_id": selected_id,
        },
    )


@router.get("/{item_id}", response_class=HTMLResponse)
async def movie_detail_fragment(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
    tab: Annotated[str, Query()] = "info",
) -> HTMLResponse:
    """Return HTMX fragment for the right movie detail pane."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.MOVIE.value:
        raise HTTPException(status_code=404, detail="Movie not found")
    ctx = await _detail_context(session, item, tab=tab)
    return render_template(request, "movies/_detail.html", ctx)


@router.post(
    "/{item_id}/edit",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def movie_edit(
    request: Request,
    session: DbSession,
    item_id: int,
    title: Annotated[str, Form()] = "",
    original_title: Annotated[str, Form()] = "",
    sort_title: Annotated[str, Form()] = "",
    year: Annotated[str, Form()] = "",
    premiered: Annotated[str, Form()] = "",
    tagline: Annotated[str, Form()] = "",
    plot: Annotated[str, Form()] = "",
    runtime: Annotated[str, Form()] = "",
    mpaa: Annotated[str, Form()] = "",
    genres: Annotated[str, Form()] = "",
    directors: Annotated[str, Form()] = "",
    writers: Annotated[str, Form()] = "",
    studios: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    collection: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Update movie metadata in DB and mark item as dirty."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.MOVIE.value:
        raise HTTPException(status_code=404, detail="Movie not found")

    meta = MovieMetadata.model_validate_json(item.metadata_json or "{}")
    meta.title = title.strip()
    meta.original_title = original_title.strip()
    meta.sort_title = sort_title.strip()
    meta.year = int(year.strip()) if year.strip().isdigit() else None
    meta.premiered = premiered.strip()
    meta.tagline = tagline.strip()
    meta.plot = plot.strip()
    meta.outline = meta.plot
    meta.runtime = int(runtime.strip()) if runtime.strip().isdigit() else None
    meta.mpaa = mpaa.strip()
    meta.genres = _split_csv(genres)
    meta.directors = _split_csv(directors)
    meta.writers = _split_csv(writers)
    meta.studios = _split_csv(studios)
    meta.tags = _split_csv(tags)
    meta.collection = collection.strip()

    item.title = meta.title or item.title
    item.year = meta.year
    item.metadata_json = meta.model_dump_json()
    item.state = ItemState.DIRTY.value
    await session.commit()

    ctx = await _detail_context(session, item, tab="info", toast="Changes staged (dirty).")
    return render_template(request, "movies/_detail.html", ctx)


@router.post(
    "/{item_id}/save",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def movie_save(
    request: Request,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    """Write movie NFO sidecar atomically to disk."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.MOVIE.value:
        raise HTTPException(status_code=404, detail="Movie not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    naming = await get_setting_value(session, SETTING_MOVIE_NAMING, "file")
    await save_movie_to_disk(session, item, library, naming_scheme=naming)
    ctx = await _detail_context(session, item, tab="info", toast="Saved NFO sidecar to disk.")
    return render_template(request, "movies/_detail.html", ctx)


@router.post(
    "/{item_id}/revert",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def movie_revert(
    request: Request,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    """Discard dirty changes and reload from disk NFO or filename."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.MOVIE.value:
        raise HTTPException(status_code=404, detail="Movie not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    await revert_movie_from_disk(session, item, library)
    ctx = await _detail_context(session, item, tab="info", toast="Reverted from disk.")
    return render_template(request, "movies/_detail.html", ctx)


@router.get("/{item_id}/artwork/{art_type}")
async def serve_movie_artwork(
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
    art_type: str,
) -> FileResponse:
    """Serve an artwork image belonging to a movie safely within its library root."""
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
        raise HTTPException(status_code=404, detail="Artwork file missing on disk")
    return FileResponse(file_path)


# --- Scrape Modal (Task 6) ---


async def _get_tmdb_provider(request: Request, session: AsyncSession) -> TMDBProvider:
    settings = request.app.state.settings
    api_key = await get_setting_value(session, SETTING_TMDB_KEY, settings.tmdb_api_key)
    cache = ProviderResponseCache(session)
    client: httpx.AsyncClient = request.app.state.http_client
    return TMDBProvider(api_key=api_key, http_client=client, cache=cache)


@router.get("/{item_id}/scrape", response_class=HTMLResponse)
async def scrape_modal(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    """Open scrape modal prefilled from filename parse."""
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    parsed = parse_movie_filename(item.rel_path)
    return render_template(
        request,
        "movies/_scrape_modal.html",
        {
            "item": item,
            "query_title": parsed.title or item.title,
            "query_year": parsed.year or item.year or "",
            "candidates": None,
            "selected_candidate": None,
            "error": None,
        },
    )


@router.post(
    "/{item_id}/scrape/search",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def scrape_search(
    request: Request,
    session: DbSession,
    item_id: int,
    title: Annotated[str, Form()],
    year: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Search TMDB for movie candidates."""
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    lang = await get_setting_value(session, SETTING_LANGUAGE, "en-US")
    parsed_year = int(year.strip()) if year.strip().isdigit() else None
    candidates = []
    error: str | None = None

    try:
        provider = await _get_tmdb_provider(request, session)
        candidates = await provider.search(
            "movie",
            SearchQuery(title=title.strip(), year=parsed_year, lang=lang),
        )
        await session.commit()
    except (MissingApiKeyError, ProviderError) as exc:
        error = str(exc)

    return render_template(
        request,
        "movies/_scrape_modal.html",
        {
            "item": item,
            "query_title": title.strip(),
            "query_year": year.strip(),
            "candidates": candidates,
            "selected_candidate": None,
            "error": error,
        },
    )


@router.get("/{item_id}/scrape/preview/{provider_id}", response_class=HTMLResponse)
async def scrape_preview(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
    provider_id: str,
) -> HTMLResponse:
    """Fetch candidate details and render field checklist before applying."""
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    lang = await get_setting_value(session, SETTING_LANGUAGE, "en-US")

    try:
        provider = await _get_tmdb_provider(request, session)
        fetched = await provider.fetch("movie", provider_id, lang)
        assert isinstance(fetched, MovieMetadata)
        artworks = await provider.artwork("movie", provider_id)
        await session.commit()
    except (MissingApiKeyError, ProviderError) as exc:
        return render_template(
            request,
            "movies/_scrape_modal.html",
            {"item": item, "error": str(exc), "query_title": item.title, "query_year": item.year},
        )

    poster_cand = next((a for a in artworks if a.type == ArtworkType.POSTER.value), None)
    fanart_cand = next((a for a in artworks if a.type == ArtworkType.FANART.value), None)
    return render_template(
        request,
        "movies/_scrape_modal.html",
        {
            "item": item,
            "query_title": item.title,
            "query_year": item.year or "",
            "selected_candidate": fetched,
            "provider_id": provider_id,
            "poster_url": poster_cand.url if poster_cand else "",
            "fanart_url": fanart_cand.url if fanart_cand else "",
            "error": None,
        },
    )


@router.post(
    "/{item_id}/scrape/apply",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def scrape_apply(
    request: Request,
    session: DbSession,
    item_id: int,
    provider_id: Annotated[str, Form()],
    fields: Annotated[list[str] | None, Form()] = None,
    poster_url: Annotated[str, Form()] = "",
    fanart_url: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Apply selected fields and artwork from TMDB candidate to the movie."""
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    selected_fields = set(fields or [])
    lang = await get_setting_value(session, SETTING_LANGUAGE, "en-US")
    naming = await get_setting_value(session, SETTING_MOVIE_NAMING, "file")

    provider = await _get_tmdb_provider(request, session)
    fetched = await provider.fetch("movie", provider_id, lang)
    assert isinstance(fetched, MovieMetadata)

    current = MovieMetadata.model_validate_json(item.metadata_json or "{}")
    if "title" in selected_fields:
        current.title = fetched.title
        current.original_title = fetched.original_title
        current.sort_title = fetched.sort_title
    if "year" in selected_fields:
        current.year = fetched.year
        current.premiered = fetched.premiered
    if "plot" in selected_fields:
        current.plot = fetched.plot
        current.outline = fetched.outline
        current.tagline = fetched.tagline
    if "runtime" in selected_fields:
        current.runtime = fetched.runtime
    if "mpaa" in selected_fields or "rating" in selected_fields:
        current.mpaa = fetched.mpaa
    if "rating" in selected_fields:
        current.rating = fetched.rating
        current.votes = fetched.votes
    if "genres" in selected_fields:
        current.genres = fetched.genres
    if "credits" in selected_fields:
        current.directors = fetched.directors
        current.writers = fetched.writers
        current.actors = fetched.actors
        current.studios = fetched.studios
        current.countries = fetched.countries

    current.tmdb_id = fetched.tmdb_id
    current.imdb_id = fetched.imdb_id

    provider_ids: dict[str, str] = json.loads(item.provider_ids_json or "{}")
    provider_ids["tmdb"] = fetched.tmdb_id
    if fetched.imdb_id:
        provider_ids["imdb"] = fetched.imdb_id

    item.title = current.title or item.title
    item.year = current.year
    item.provider_ids_json = json.dumps(provider_ids)
    item.metadata_json = current.model_dump_json()
    item.state = ItemState.DIRTY.value

    # Download selected artwork
    root = Path(library.root_path).resolve()
    video_path = resolve_within_root(item.rel_path, root)
    http_client: httpx.AsyncClient = request.app.state.http_client

    for art_type, url, field_key in [
        (ArtworkType.POSTER.value, poster_url.strip(), "poster"),
        (ArtworkType.FANART.value, fanart_url.strip(), "fanart"),
    ]:
        if field_key in selected_fields and url:
            target = resolve_movie_artwork_target(video_path, art_type, naming_scheme=naming)
            try:
                dl = await download_artwork(http_client, url, target)
                rel_art = dl.path.relative_to(root).as_posix()
                existing_art = (
                    await session.execute(
                        select(Artwork).where(Artwork.item_id == item.id, Artwork.type == art_type)
                    )
                ).scalar_one_or_none()
                if existing_art is None:
                    session.add(
                        Artwork(
                            item_id=item.id,
                            type=art_type,
                            rel_path=rel_art,
                            source_url=url,
                            width=dl.width,
                            height=dl.height,
                        )
                    )
                else:
                    existing_art.rel_path = rel_art
                    existing_art.source_url = url
                    existing_art.width = dl.width
                    existing_art.height = dl.height
            except ArtworkDownloadError:
                pass

    await session.commit()
    ctx = await _detail_context(
        session,
        item,
        tab="info",
        toast="Applied scraped metadata. Click Save to write NFO.",
    )
    return render_template(request, "movies/_detail.html", ctx)


def _get_opensubtitles_provider(request: Request, session: AsyncSession) -> OpenSubtitlesProvider:
    settings = request.app.state.settings
    return OpenSubtitlesProvider(
        api_key=settings.opensubtitles_api_key,
        username=settings.opensubtitles_username,
        password=settings.opensubtitles_password,
        http_client=request.app.state.http_client,
        cache=ProviderResponseCache(session),
    )


@router.post(
    "/{item_id}/subtitles/search",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def movie_subtitles_search(
    request: Request,
    session: DbSession,
    item_id: int,
    languages: Annotated[str, Form()] = "en",
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    video_path = resolve_within_root(item.rel_path, Path(library.root_path).resolve())
    meta = MovieMetadata.model_validate_json(item.metadata_json or "{}")
    sub_candidates: list[SubtitleCandidate] = []
    sub_error: str | None = None
    try:
        prov = _get_opensubtitles_provider(request, session)
        sub_candidates = await prov.search(
            SubtitleQuery(
                title=meta.title or item.title,
                year=meta.year or item.year,
                tmdb_id=meta.tmdb_id,
                imdb_id=meta.imdb_id,
                movie_hash=compute_opensubtitles_hash(video_path),
                languages=_split_csv(languages) or ["en"],
            )
        )
        await session.commit()
    except (MissingApiKeyError, QuotaExceededError, ProviderError) as exc:
        sub_error = str(exc)

    ctx = await _detail_context(session, item, tab="subtitles")
    ctx["sub_candidates"] = sub_candidates
    ctx["sub_error"] = sub_error
    return render_template(request, "movies/_detail.html", ctx)


@router.post(
    "/{item_id}/subtitles/download",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def movie_subtitles_download(
    request: Request,
    session: DbSession,
    item_id: int,
    file_id: Annotated[str, Form()],
    lang: Annotated[str, Form()] = "en",
    forced: Annotated[str, Form()] = "false",
    hearing_impaired: Annotated[str, Form()] = "false",
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    root = Path(library.root_path).resolve()
    video_path = resolve_within_root(item.rel_path, root)
    is_forced = forced.lower() == "true"
    is_hi = hearing_impaired.lower() == "true"

    toast: str | None = None
    sub_error: str | None = None
    try:
        prov = _get_opensubtitles_provider(request, session)
        dl = await prov.download(
            SubtitleCandidate(
                provider="opensubtitles",
                provider_id=file_id,
                file_id=file_id,
                lang=lang,
                forced=is_forced,
                hearing_impaired=is_hi,
            )
        )
        written = write_subtitle_file(
            video_path,
            lang,
            dl.content,
            forced=is_forced,
            hearing_impaired=is_hi,
            overwrite=False,
        )
        session.add(
            SidecarFile(
                item_id=item.id,
                kind="subtitle",
                rel_path=written.relative_to(root).as_posix(),
                lang=lang,
                format="srt",
                synced=False,
                source="opensubtitles",
                source_id=file_id,
            )
        )
        await session.commit()
        toast = f"Downloaded subtitle: {written.name}"
    except (SubtitleExistsError, MissingApiKeyError, QuotaExceededError, ProviderError) as exc:
        sub_error = str(exc)

    ctx = await _detail_context(session, item, tab="subtitles", toast=toast)
    ctx["sub_error"] = sub_error
    return render_template(request, "movies/_detail.html", ctx)
