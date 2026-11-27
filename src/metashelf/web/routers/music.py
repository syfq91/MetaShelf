"""Music library view, Artist -> Album -> Track tree, and NFO saving."""

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.auth.deps import CurrentUser, DbSession, require_csrf
from metashelf.db.models import Artwork, Item, Library, SidecarFile
from metashelf.domain.models import (
    AlbumMetadata,
    ArtistMetadata,
    ItemKind,
    ItemState,
    TrackMetadata,
)
from metashelf.providers.base import LyricsQuery
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.lrclib import LRCLIBProvider
from metashelf.services.paths import PathTraversalError, resolve_within_root
from metashelf.web.templating import get_nav_context, render_template
from metashelf.writers.kodi_nfo_music import write_album_nfo, write_artist_nfo
from metashelf.writers.lyrics import LyricsExistsError, find_existing_lyrics, write_lyrics_file

router = APIRouter(prefix="/music", tags=["music"])


async def _resolve_artist_for_item(session: AsyncSession, item: Item) -> Item:
    if item.kind == ItemKind.ARTIST.value:
        return item
    if item.kind == ItemKind.ALBUM.value and item.parent_id is not None:
        parent = await session.get(Item, item.parent_id)
        if parent is not None:
            return parent
    if item.kind == ItemKind.TRACK.value and item.parent_id is not None:
        alb = await session.get(Item, item.parent_id)
        if alb is not None and alb.parent_id is not None:
            art = await session.get(Item, alb.parent_id)
            if art is not None:
                return art
    return item


async def _load_music_tree(session: AsyncSession, artist_item: Item) -> list[dict[str, Any]]:
    albums = (
        await session.execute(
            select(Item)
            .where(Item.parent_id == artist_item.id, Item.kind == ItemKind.ALBUM.value)
            .order_by(Item.year.asc().nullslast(), Item.title.asc())
        )
    ).scalars().all()
    tree: list[dict[str, Any]] = []
    for alb in albums:
        tracks = (
            await session.execute(
                select(Item)
                .where(Item.parent_id == alb.id, Item.kind == ItemKind.TRACK.value)
                .order_by(Item.rel_path)
            )
        ).scalars().all()
        tree.append({"album": alb, "tracks": list(tracks)})
    return tree


async def _music_detail_context(
    session: AsyncSession,
    item: Item,
    toast: str | None = None,
) -> dict[str, Any]:
    artist_item = await _resolve_artist_for_item(session, item)
    tree = await _load_music_tree(session, artist_item)
    arts = (
        await session.execute(select(Artwork).where(Artwork.item_id == item.id))
    ).scalars().all()
    art_map = {a.type: a for a in arts}

    artist_meta: ArtistMetadata | None = None
    album_meta: AlbumMetadata | None = None
    track_meta: TrackMetadata | None = None
    lyrics_text: str = ""
    lyrics_file_name: str = ""
    if item.kind == ItemKind.ARTIST.value:
        artist_meta = ArtistMetadata.model_validate_json(item.metadata_json or "{}")
    elif item.kind == ItemKind.ALBUM.value:
        album_meta = AlbumMetadata.model_validate_json(item.metadata_json or "{}")
    else:
        track_meta = TrackMetadata.model_validate_json(item.metadata_json or "{}")
        library = await session.get(Library, item.library_id)
        if library is not None:
            audio_path = resolve_within_root(item.rel_path, Path(library.root_path).resolve())
            existing_lyrics = find_existing_lyrics(audio_path)
            if existing_lyrics is not None:
                lyrics_file_name = existing_lyrics.name
                lyrics_text = existing_lyrics.read_text(encoding="utf-8", errors="replace")

    return {
        "item": item,
        "artist_item": artist_item,
        "tree": tree,
        "art_map": art_map,
        "artist_meta": artist_meta,
        "album_meta": album_meta,
        "track_meta": track_meta,
        "lyrics_text": lyrics_text,
        "lyrics_file_name": lyrics_file_name,
        "toast": toast,
    }


@router.get("", response_class=HTMLResponse)
async def music_index(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    q: Annotated[str, Query()] = "",
    selected_id: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render two-pane Music library view."""
    nav_ctx = await get_nav_context(session)
    stmt = select(Item).where(Item.kind == ItemKind.ARTIST.value)
    if q.strip():
        stmt = stmt.where(Item.title.ilike(f"%{q.strip()}%"))
    artists = list((await session.execute(stmt.order_by(Item.title.asc()))).scalars().all())

    selected_item: Item | None = None
    if selected_id is not None:
        selected_item = await session.get(Item, selected_id)
    elif artists:
        selected_item = artists[0]

    detail_ctx = await _music_detail_context(session, selected_item) if selected_item else {}
    return render_template(
        request,
        "music/index.html",
        {
            "active_nav": "music",
            "q": q,
            "artists": artists,
            "selected_item": selected_item,
            **nav_ctx,
            **detail_ctx,
        },
    )


@router.get("/{item_id}", response_class=HTMLResponse)
async def music_detail_fragment(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None or item.kind not in {
        ItemKind.ARTIST.value,
        ItemKind.ALBUM.value,
        ItemKind.TRACK.value,
    }:
        raise HTTPException(status_code=404, detail="Music item not found")
    ctx = await _music_detail_context(session, item)
    return render_template(request, "music/_detail.html", ctx)


@router.post(
    "/{item_id}/edit",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def music_edit(
    request: Request,
    session: DbSession,
    item_id: int,
    title: Annotated[str, Form()] = "",
    year: Annotated[str, Form()] = "",
    label: Annotated[str, Form()] = "",
    biography: Annotated[str, Form()] = "",
    review: Annotated[str, Form()] = "",
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Music item not found")

    if item.kind == ItemKind.ARTIST.value:
        a_meta = ArtistMetadata.model_validate_json(item.metadata_json or "{}")
        a_meta.name = title.strip()
        a_meta.biography = biography.strip()
        item.title = a_meta.name or item.title
        item.metadata_json = a_meta.model_dump_json()
        item.state = ItemState.DIRTY.value
    elif item.kind == ItemKind.ALBUM.value:
        alb_meta = AlbumMetadata.model_validate_json(item.metadata_json or "{}")
        alb_meta.title = title.strip()
        alb_meta.year = int(year.strip()) if year.strip().isdigit() else None
        alb_meta.label = label.strip()
        alb_meta.review = review.strip()
        item.title = alb_meta.title or item.title
        item.year = alb_meta.year
        item.metadata_json = alb_meta.model_dump_json()
        item.state = ItemState.DIRTY.value

    await session.commit()
    ctx = await _music_detail_context(session, item, toast="Changes staged (dirty).")
    return render_template(request, "music/_detail.html", ctx)


@router.post(
    "/{item_id}/save",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def music_save(
    request: Request,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Music item not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    root = Path(library.root_path).resolve()
    target_dir = resolve_within_root(item.rel_path, root)
    if item.kind == ItemKind.ARTIST.value:
        a_meta = ArtistMetadata.model_validate_json(item.metadata_json or "{}")
        write_artist_nfo(target_dir / "artist.nfo", a_meta)
        item.state = ItemState.COMPLETE.value
    elif item.kind == ItemKind.ALBUM.value:
        alb_meta = AlbumMetadata.model_validate_json(item.metadata_json or "{}")
        write_album_nfo(target_dir / "album.nfo", alb_meta)
        item.state = ItemState.COMPLETE.value

    await session.commit()
    ctx = await _music_detail_context(session, item, toast="Saved NFO sidecar to disk.")
    return render_template(request, "music/_detail.html", ctx)


@router.get("/{item_id}/artwork/{art_type}")
async def serve_music_artwork(
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


@router.post(
    "/{item_id}/lyrics/fetch",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def fetch_track_lyrics_route(
    request: Request,
    session: DbSession,
    item_id: int,
) -> HTMLResponse:
    """Fetch lyrics for a single track from LRCLIB and save .lrc or .txt."""
    item = await session.get(Item, item_id)
    if item is None or item.kind != ItemKind.TRACK.value:
        raise HTTPException(status_code=404, detail="Track not found")
    library = await session.get(Library, item.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    root = Path(library.root_path).resolve()
    audio_path = resolve_within_root(item.rel_path, root)
    t_meta = TrackMetadata.model_validate_json(item.metadata_json or "{}")
    dur_s = int(t_meta.duration_ms / 1000) if t_meta.duration_ms else None

    prov = LRCLIBProvider(
        http_client=request.app.state.http_client,
        cache=ProviderResponseCache(session),
    )
    cands = await prov.search(
        LyricsQuery(
            title=t_meta.title or item.title,
            artist=t_meta.artist,
            album=t_meta.album,
            duration_seconds=dur_s,
        )
    )
    toast = "No lyrics found on LRCLIB."
    if cands:
        best = cands[0]
        try:
            written = write_lyrics_file(audio_path, best.text, synced=best.synced, overwrite=False)
            session.add(
                SidecarFile(
                    item_id=item.id,
                    kind="lyrics",
                    rel_path=written.relative_to(root).as_posix(),
                    format=best.format,
                    synced=best.synced,
                    source="lrclib",
                    source_id=best.provider_id,
                )
            )
            await session.commit()
            toast = f"Saved lyrics: {written.name}"
        except LyricsExistsError:
            toast = "Lyrics file already exists on disk."

    ctx = await _music_detail_context(session, item, toast=toast)
    return render_template(request, "music/_detail.html", ctx)
