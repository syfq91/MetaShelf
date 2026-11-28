"""TV Shows library view, tree navigation, scrape modal, and batch episode fetch."""

import json
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.auth.deps import CurrentUser, DbSession, require_csrf
from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import (
    EpisodeMetadata,
    ItemKind,
    ItemState,
    SeasonMetadata,
    ShowMetadata,
)
from metashelf.jobs.queue import JobWorker, enqueue_job
from metashelf.providers.base import MissingApiKeyError, ProviderError, SearchQuery
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.tmdb import TMDBProvider
from metashelf.scanner.parser import parse_show_folder_name
from metashelf.services.paths import PathTraversalError, resolve_within_root
from metashelf.services.tv_save import save_episode_to_disk, save_show_to_disk
from metashelf.web.routers.settings import SETTING_LANGUAGE, SETTING_TMDB_KEY, get_setting_value
from metashelf.web.templating import get_nav_context, render_template

router = APIRouter(prefix="/tv", tags=["tv"])


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


async def _load_show_tree(
    session: AsyncSession,
    show_item: Item,
) -> list[dict[str, Any]]:
    """Build Show -> Season -> Episode tree structure for the detail pane."""
    seasons = (
        await session.execute(
            select(Item)
            .where(Item.parent_id == show_item.id, Item.kind == ItemKind.SEASON.value)
            .order_by(Item.rel_path)
        )
    ).scalars().all()

    tree: list[dict[str, Any]] = []
    for s in seasons:
        eps = (
            await session.execute(
                select(Item)
                .where(Item.parent_id == s.id, Item.kind == ItemKind.EPISODE.value)
                .order_by(Item.rel_path)
            )
        ).scalars().all()
        tree.append({"season": s, "episodes": list(eps)})
    return tree


async def _resolve_show_for_item(session: AsyncSession, item: Item) -> Item:
    if item.kind == ItemKind.SHOW.value:
        return item
    if item.kind == ItemKind.SEASON.value and item.parent_id is not None:
        parent = await session.get(Item, item.parent_id)
        if parent is not None:
            return parent
    if item.kind == ItemKind.EPISODE.value and item.parent_id is not None:
        season = await session.get(Item, item.parent_id)
        if season is not None and season.parent_id is not None:
            show = await session.get(Item, season.parent_id)
            if show is not None:
                return show
    return item


async def _tv_detail_context(
    session: AsyncSession,
    item: Item,
    toast: str | None = None,
) -> dict[str, Any]:
    show_item = await _resolve_show_for_item(session, item)
    tree = await _load_show_tree(session, show_item)
    arts = (
        await session.execute(select(Artwork).where(Artwork.item_id == item.id))
    ).scalars().all()
    art_map = {a.type: a for a in arts}

    show_meta: ShowMetadata | None = None
    season_meta: SeasonMetadata | None = None
    ep_meta: EpisodeMetadata | None = None
    if item.kind == ItemKind.SHOW.value:
        show_meta = ShowMetadata.model_validate_json(item.metadata_json or "{}")
    elif item.kind == ItemKind.SEASON.value:
        season_meta = SeasonMetadata.model_validate_json(item.metadata_json or "{}")
    else:
        ep_meta = EpisodeMetadata.model_validate_json(item.metadata_json or "{}")

    return {
        "item": item,
        "show_item": show_item,
        "tree": tree,
        "art_map": art_map,
        "show_meta": show_meta,
        "season_meta": season_meta,
        "ep_meta": ep_meta,
        "toast": toast,
    }


def _episode_code(ep_meta: EpisodeMetadata) -> str:
    ep_nums = ep_meta.episodes or [ep_meta.episode]
    return f"S{ep_meta.season:02d}" + "".join(f"E{n:02d}" for n in ep_nums)


async def _load_shows_with_trees(
    session: AsyncSession,
    shows: list[Item],
) -> list[dict[str, Any]]:
    """Build Show -> Season -> Episode tree for the middle-column list in 2 batch queries."""
    if not shows:
        return []

    show_ids = [s.id for s in shows]
    seasons = list(
        (
            await session.execute(
                select(Item)
                .where(Item.parent_id.in_(show_ids), Item.kind == ItemKind.SEASON.value)
                .order_by(Item.rel_path)
            )
        ).scalars().all()
    )

    season_ids = [se.id for se in seasons]
    episodes: list[Item] = []
    if season_ids:
        episodes = list(
            (
                await session.execute(
                    select(Item)
                    .where(Item.parent_id.in_(season_ids), Item.kind == ItemKind.EPISODE.value)
                    .order_by(Item.rel_path)
                )
            ).scalars().all()
        )

    eps_by_season: dict[int, list[dict[str, Any]]] = {}
    for ep in episodes:
        if ep.parent_id is None:
            continue
        ep_meta = EpisodeMetadata.model_validate_json(ep.metadata_json or "{}")
        code = _episode_code(ep_meta)
        display_title = "" if ep.title == code else ep.title
        eps_by_season.setdefault(ep.parent_id, []).append(
            {
                "item": ep,
                "code": code,
                "title": display_title,
                "sort_key": (ep_meta.season, ep_meta.episode, ep.rel_path),
            }
        )
    for ep_list in eps_by_season.values():
        ep_list.sort(key=lambda e: e["sort_key"])

    seasons_by_show: dict[int, list[dict[str, Any]]] = {}
    for se in seasons:
        if se.parent_id is None:
            continue
        seasons_by_show.setdefault(se.parent_id, []).append(
            {
                "season": se,
                "episodes": eps_by_season.get(se.id, []),
            }
        )

    return [
        {
            "show": s,
            "seasons": seasons_by_show.get(s.id, []),
        }
        for s in shows
    ]


@router.get("", response_class=HTMLResponse)
async def tv_index(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    q: Annotated[str, Query()] = "",
    selected_id: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render two-pane TV Shows view with expandable Show -> Season -> Episode tree."""
    nav_ctx = await get_nav_context(session)
    stmt = select(Item).where(Item.kind == ItemKind.SHOW.value)
    if q.strip():
        stmt = stmt.where(Item.title.ilike(f"%{q.strip()}%"))
    shows = list((await session.execute(stmt.order_by(Item.title.asc()))).scalars().all())
    show_trees = await _load_shows_with_trees(session, shows)
    total_episodes = sum(len(se["episodes"]) for t in show_trees for se in t["seasons"])

    selected_item: Item | None = None
    if selected_id is not None:
        selected_item = await session.get(Item, selected_id)
    elif shows:
        selected_item = shows[0]

    detail_ctx = await _tv_detail_context(session, selected_item) if selected_item else {}
    return render_template(
        request,
        "tv/index.html",
        {
            "active_nav": "tv",
            "q": q,
            "shows": shows,
            "show_trees": show_trees,
            "total_episodes": total_episodes,
            "selected_item": selected_item,
            **nav_ctx,
            **detail_ctx,
        },
    )


@router.get("/{item_id}", response_class=HTMLResponse)
async def tv_detail_fragment(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    """Render HTMX detail pane for a show, season, or episode."""
    item = await session.get(Item, item_id)
    if item is None or item.kind not in {
        ItemKind.SHOW.value,
        ItemKind.SEASON.value,
        ItemKind.EPISODE.value,
    }:
        raise HTTPException(status_code=404, detail="TV item not found")
    ctx = await _tv_detail_context(session, item)
    return render_template(request, "tv/_detail.html", ctx)


@router.post(
    "/{item_id}/edit",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def tv_edit(
    request: Request,
    session: DbSession,
    item_id: int,
    title: Annotated[str, Form()] = "",
    year: Annotated[str, Form()] = "",
    status_val: Annotated[str, Form()] = "",
    plot: Annotated[str, Form()] = "",
    genres: Annotated[str, Form()] = "",
    aired: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Stage edits for a show or episode."""
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="TV item not found")

    if item.kind == ItemKind.SHOW.value:
        meta = ShowMetadata.model_validate_json(item.metadata_json or "{}")
        meta.title = title.strip()
        meta.year = int(year.strip()) if year.strip().isdigit() else None
        meta.status = status_val.strip()
        meta.plot = plot.strip()
        meta.outline = meta.plot
        meta.genres = _split_csv(genres)
        item.title = meta.title or item.title
        item.year = meta.year
        item.metadata_json = meta.model_dump_json()
        item.state = ItemState.DIRTY.value
    elif item.kind == ItemKind.EPISODE.value:
        ep_meta = EpisodeMetadata.model_validate_json(item.metadata_json or "{}")
        ep_meta.title = title.strip()
        ep_meta.aired = aired.strip()
        ep_meta.plot = plot.strip()
        item.title = ep_meta.title or item.title
        item.metadata_json = ep_meta.model_dump_json()
        item.state = ItemState.DIRTY.value

    await session.commit()
    ctx = await _tv_detail_context(session, item, toast="Changes staged (dirty).")
    return render_template(request, "tv/_detail.html", ctx)


@router.post(
    "/{item_id}/save",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def tv_save(
    request: Request,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    """Write tvshow.nfo or <episode>.nfo atomically."""
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="TV item not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    if item.kind == ItemKind.SHOW.value:
        await save_show_to_disk(session, item, library)
    elif item.kind == ItemKind.EPISODE.value:
        await save_episode_to_disk(session, item, library)

    ctx = await _tv_detail_context(session, item, toast="Saved NFO sidecar to disk.")
    return render_template(request, "tv/_detail.html", ctx)


@router.get("/{item_id}/artwork/{art_type}")
async def serve_tv_artwork(
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
    art_type: str,
) -> FileResponse:
    """Serve TV artwork safely within library root."""
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
        raise HTTPException(status_code=404, detail="Artwork file missing")
    return FileResponse(file_path)


async def _get_tmdb_provider(request: Request, session: AsyncSession) -> TMDBProvider:
    settings = request.app.state.settings
    api_key = await get_setting_value(session, SETTING_TMDB_KEY, settings.tmdb_api_key)
    cache = ProviderResponseCache(session)
    client: httpx.AsyncClient = request.app.state.http_client
    return TMDBProvider(api_key=api_key, http_client=client, cache=cache)


@router.get("/{show_id}/scrape", response_class=HTMLResponse)
async def tv_scrape_modal(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    show_id: int,
) -> HTMLResponse:
    """Open TMDB scrape modal for a TV show."""
    show = await session.get(Item, show_id)
    if show is None or show.kind != ItemKind.SHOW.value:
        raise HTTPException(status_code=404, detail="Show not found")
    parsed = parse_show_folder_name(Path(show.rel_path).name)
    return render_template(
        request,
        "tv/_scrape_modal.html",
        {
            "show": show,
            "query_title": parsed.title or show.title,
            "query_year": parsed.year or show.year or "",
            "candidates": None,
            "error": None,
        },
    )


@router.post(
    "/{show_id}/scrape/search",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def tv_scrape_search(
    request: Request,
    session: DbSession,
    show_id: int,
    title: Annotated[str, Form()],
    year: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Search TMDB for TV show candidates."""
    show = await session.get(Item, show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")
    lang = await get_setting_value(session, SETTING_LANGUAGE, "en-US")
    parsed_year = int(year.strip()) if year.strip().isdigit() else None
    candidates = []
    error: str | None = None
    try:
        provider = await _get_tmdb_provider(request, session)
        candidates = await provider.search(
            "show",
            SearchQuery(title=title.strip(), year=parsed_year, lang=lang),
        )
        await session.commit()
    except (MissingApiKeyError, ProviderError) as exc:
        error = str(exc)

    return render_template(
        request,
        "tv/_scrape_modal.html",
        {
            "show": show,
            "query_title": title.strip(),
            "query_year": year.strip(),
            "candidates": candidates,
            "error": error,
        },
    )


@router.post(
    "/{show_id}/scrape/apply",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def tv_scrape_apply(
    request: Request,
    session: DbSession,
    show_id: int,
    provider_id: Annotated[str, Form()],
) -> HTMLResponse:
    """Match a TV show to TMDB, save tvshow.nfo, and enqueue batch episode fetch."""
    show = await session.get(Item, show_id)
    if show is None or show.kind != ItemKind.SHOW.value:
        raise HTTPException(status_code=404, detail="Show not found")

    lang = await get_setting_value(session, SETTING_LANGUAGE, "en-US")
    provider = await _get_tmdb_provider(request, session)
    fetched = await provider.fetch("show", provider_id, lang)
    assert isinstance(fetched, ShowMetadata)

    pids: dict[str, str] = {"tmdb": fetched.tmdb_id or provider_id}
    if fetched.tvdb_id:
        pids["tvdb"] = fetched.tvdb_id
    if fetched.imdb_id:
        pids["imdb"] = fetched.imdb_id

    show.title = fetched.title or show.title
    show.year = fetched.year
    show.provider_ids_json = json.dumps(pids)
    show.metadata_json = fetched.model_dump_json()
    show.state = ItemState.MATCHED.value
    await session.commit()

    job = await enqueue_job(session, "fetch_show_episodes", {"show_id": show.id})
    worker: JobWorker = request.app.state.job_worker
    worker.notify_new_job()

    ctx = await _tv_detail_context(
        session,
        show,
        toast=f"Matched '{show.title}'. Queued episode fetch job #{job.id}.",
    )
    return render_template(request, "tv/_detail.html", ctx)


@router.post(
    "/{show_id}/fetch-episodes",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def tv_fetch_episodes(
    request: Request,
    session: DbSession,
    show_id: int,
) -> HTMLResponse:
    """Enqueue batch episode fetch for an already-matched show."""
    show = await session.get(Item, show_id)
    if show is None or show.kind != ItemKind.SHOW.value:
        raise HTTPException(status_code=404, detail="Show not found")
    job = await enqueue_job(session, "fetch_show_episodes", {"show_id": show.id})
    worker: JobWorker = request.app.state.job_worker
    worker.notify_new_job()
    ctx = await _tv_detail_context(
        session,
        show,
        toast=f"Queued episode fetch job #{job.id}.",
    )
    return render_template(request, "tv/_detail.html", ctx)
