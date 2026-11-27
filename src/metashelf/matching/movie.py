"""Movie candidate scoring and auto-matching."""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import ArtworkType, ItemState, MovieMetadata
from metashelf.providers.base import Candidate, SearchQuery
from metashelf.providers.tmdb import TMDBProvider
from metashelf.scanner.parser import parse_movie_filename
from metashelf.services.movie_save import resolve_movie_artwork_target, save_movie_to_disk
from metashelf.services.paths import resolve_within_root
from metashelf.writers.artwork import ArtworkDownloadError, download_artwork


def _normalize_title(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    return " ".join(cleaned.split())


def score_movie_candidate(
    query_title: str,
    query_year: int | None,
    candidate: Candidate,
) -> float:
    """Score a movie candidate in [0.0, 1.0] using title similarity and release year."""
    norm_q = _normalize_title(query_title)
    norm_c = _normalize_title(candidate.title)
    norm_orig = _normalize_title(candidate.original_title) if candidate.original_title else ""

    title_sim = SequenceMatcher(None, norm_q, norm_c).ratio()
    if norm_orig:
        title_sim = max(title_sim, SequenceMatcher(None, norm_q, norm_orig).ratio())

    if query_year is None or candidate.year is None:
        year_score = 0.15
    elif query_year == candidate.year:
        year_score = 0.30
    elif abs(query_year - candidate.year) == 1:
        year_score = 0.15
    else:
        year_score = 0.0

    return round(title_sim * 0.70 + year_score, 4)


def pick_auto_match(
    query_title: str,
    query_year: int | None,
    candidates: list[Candidate],
    min_confidence: float = 0.80,
    min_margin: float = 0.15,
) -> Candidate | None:
    """Pick the top candidate only if it passes confidence and margin thresholds."""
    if not candidates:
        return None

    scored = sorted(
        ((score_movie_candidate(query_title, query_year, c), c) for c in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    top_score, top_candidate = scored[0]
    if top_score < min_confidence:
        return None
    if len(scored) > 1:
        second_score = scored[1][0]
        if (top_score - second_score) < min_margin:
            return None
    return top_candidate


async def auto_match_movie_item(
    session: AsyncSession,
    item: Item,
    library: Library,
    provider: TMDBProvider,
    http_client: httpx.AsyncClient,
    lang: str = "en-US",
    naming_scheme: str = "file",
) -> bool:
    """Auto-match a single unmatched movie item, fetch metadata/artwork, and save NFO."""
    existing_ids: dict[str, str] = json.loads(item.provider_ids_json or "{}")
    if existing_ids or item.state == ItemState.DIRTY.value:
        return False

    parsed = parse_movie_filename(item.rel_path)
    query_title = parsed.title or item.title
    query_year = parsed.year or item.year

    candidates = await provider.search(
        "movie",
        SearchQuery(title=query_title, year=query_year, lang=lang),
    )
    chosen = pick_auto_match(query_title, query_year, candidates)
    if chosen is None:
        return False

    meta = await provider.fetch("movie", chosen.provider_id, lang)
    assert isinstance(meta, MovieMetadata)
    artworks = await provider.artwork("movie", chosen.provider_id)

    provider_ids = {"tmdb": chosen.provider_id}
    if meta.imdb_id:
        provider_ids["imdb"] = meta.imdb_id

    item.title = meta.title or item.title
    item.year = meta.year
    item.provider_ids_json = json.dumps(provider_ids)
    item.metadata_json = meta.model_dump_json()

    root = Path(library.root_path).resolve()
    video_path = resolve_within_root(item.rel_path, root)

    for art_type in (ArtworkType.POSTER.value, ArtworkType.FANART.value):
        cand = next((a for a in artworks if a.type == art_type), None)
        if cand is None:
            continue
        target = resolve_movie_artwork_target(video_path, art_type, naming_scheme=naming_scheme)
        try:
            dl = await download_artwork(http_client, cand.url, target)
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
                        source_url=cand.url,
                        width=dl.width,
                        height=dl.height,
                    )
                )
            else:
                existing_art.rel_path = rel_art
                existing_art.source_url = cand.url
                existing_art.width = dl.width
                existing_art.height = dl.height
        except ArtworkDownloadError:
            pass

    await save_movie_to_disk(session, item, library, naming_scheme=naming_scheme)
    return True
