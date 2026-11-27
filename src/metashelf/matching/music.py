"""Music artist and album release disambiguation and auto-matching."""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item, Library
from metashelf.domain.models import (
    AlbumMetadata,
    ArtistMetadata,
    ArtworkType,
    ItemKind,
    ItemState,
    TrackInfo,
)
from metashelf.providers.base import Candidate, SearchQuery
from metashelf.providers.coverart import CoverArtArchiveProvider
from metashelf.providers.musicbrainz import MusicBrainzProvider
from metashelf.services.paths import resolve_within_root
from metashelf.writers.artwork import ArtworkDownloadError, download_artwork
from metashelf.writers.kodi_nfo_music import write_album_nfo, write_artist_nfo


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", s.lower()).split())


def score_album_release(
    album_title: str,
    artist_name: str,
    year: int | None,
    local_tracks: list[TrackInfo],
    candidate: Candidate,
    candidate_tracks: list[TrackInfo] | None = None,
) -> float:
    """Score a MusicBrainz release candidate using title, artist, year, track count, and titles."""
    title_sim = SequenceMatcher(None, _norm(album_title), _norm(candidate.title)).ratio()
    cand_artist = candidate.extra.get("artist", "")
    artist_sim = (
        SequenceMatcher(None, _norm(artist_name), _norm(cand_artist)).ratio()
        if artist_name and cand_artist
        else 0.5
    )

    if year is not None and candidate.year is not None:
        if year == candidate.year:
            year_score = 1.0
        elif abs(year - candidate.year) == 1:
            year_score = 0.5
        else:
            year_score = 0.0
    else:
        year_score = 0.5

    # Track count match (crucial for disambiguating editions)
    local_count = len(local_tracks)
    cand_count_raw = candidate.extra.get("track_count", "0")
    cand_count = int(cand_count_raw) if cand_count_raw.isdigit() else 0
    if local_count > 0 and cand_count > 0:
        diff = abs(local_count - cand_count)
        count_score = 1.0 if diff == 0 else max(0.0, 1.0 - (diff / max(local_count, cand_count)))
    else:
        count_score = 0.5

    # Optional track title similarity when candidate tracks are available
    if local_tracks and candidate_tracks:
        pairs = zip(
            sorted(local_tracks, key=lambda t: (t.disc, t.position)),
            sorted(candidate_tracks, key=lambda t: (t.disc, t.position)),
            strict=False,
        )
        sims = [
            SequenceMatcher(None, _norm(lt.title), _norm(ct.title)).ratio()
            for lt, ct in pairs
        ]
        track_title_score = sum(sims) / len(sims) if sims else 0.5
    else:
        track_title_score = 0.5

    return round(
        title_sim * 0.30
        + artist_sim * 0.15
        + year_score * 0.15
        + count_score * 0.25
        + track_title_score * 0.15,
        4,
    )


def pick_album_release(
    album_title: str,
    artist_name: str,
    year: int | None,
    local_tracks: list[TrackInfo],
    candidates: list[Candidate],
    min_confidence: float = 0.70,
) -> Candidate | None:
    """Select the highest-scoring MusicBrainz release above confidence threshold."""
    if not candidates:
        return None
    scored = sorted(
        (
            (score_album_release(album_title, artist_name, year, local_tracks, c), c)
            for c in candidates
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    top_score, top_cand = scored[0]
    if top_score < min_confidence:
        return None
    return top_cand


async def auto_match_music_library(
    session: AsyncSession,
    library: Library,
    mb: MusicBrainzProvider,
    caa: CoverArtArchiveProvider,
    http_client: httpx.AsyncClient,
) -> int:
    """Auto-match unmatched artists and albums in a music library."""
    root = Path(library.root_path).resolve()
    matched_count = 0

    artists = (
        await session.execute(
            select(Item).where(
                Item.library_id == library.id,
                Item.kind == ItemKind.ARTIST.value,
            )
        )
    ).scalars().all()

    for artist_item in artists:
        a_pids: dict[str, str] = json.loads(artist_item.provider_ids_json or "{}")
        is_unmatched = not a_pids and artist_item.state != ItemState.DIRTY.value
        if is_unmatched and artist_item.rel_path != "__root__":
            a_cands = await mb.search("artist", SearchQuery(title=artist_item.title))
            if a_cands:
                best_a = a_cands[0]
                a_meta = await mb.fetch("artist", best_a.provider_id, "en")
                assert isinstance(a_meta, ArtistMetadata)
                artist_item.title = a_meta.name or artist_item.title
                artist_item.provider_ids_json = json.dumps({"musicbrainz": best_a.provider_id})
                artist_item.metadata_json = a_meta.model_dump_json()
                artist_dir = resolve_within_root(artist_item.rel_path, root)
                write_artist_nfo(artist_dir / "artist.nfo", a_meta)
                artist_item.sidecar_mtime = (artist_dir / "artist.nfo").stat().st_mtime
                artist_item.state = ItemState.COMPLETE.value
                matched_count += 1

    albums = (
        await session.execute(
            select(Item).where(
                Item.library_id == library.id,
                Item.kind == ItemKind.ALBUM.value,
            )
        )
    ).scalars().all()

    for alb_item in albums:
        alb_pids: dict[str, str] = json.loads(alb_item.provider_ids_json or "{}")
        if alb_pids or alb_item.state == ItemState.DIRTY.value:
            continue

        local_meta = AlbumMetadata.model_validate_json(alb_item.metadata_json or "{}")
        cands = await mb.search(
            "album",
            SearchQuery(title=local_meta.title or alb_item.title, year=alb_item.year),
        )
        chosen = pick_album_release(
            local_meta.title or alb_item.title,
            local_meta.artist,
            alb_item.year,
            local_meta.tracks,
            cands,
        )
        if chosen is None:
            continue

        fetched = await mb.fetch("album", chosen.provider_id, "en")
        assert isinstance(fetched, AlbumMetadata)
        alb_item.title = fetched.title or alb_item.title
        alb_item.year = fetched.year
        alb_item.provider_ids_json = json.dumps({"musicbrainz": chosen.provider_id})
        alb_item.metadata_json = fetched.model_dump_json()

        alb_dir = resolve_within_root(alb_item.rel_path, root)
        write_album_nfo(alb_dir / "album.nfo", fetched)
        alb_item.sidecar_mtime = (alb_dir / "album.nfo").stat().st_mtime

        # Fetch front cover via Cover Art Archive
        arts = await caa.artwork(
            "album",
            chosen.provider_id,
            release_group_id=fetched.musicbrainz_release_group_id,
        )
        has_cover = False
        if arts:
            cover_target = alb_dir / "folder.jpg"
            try:
                dl = await download_artwork(
                    http_client, arts[0].url, cover_target, allow_redirects=True
                )
                rel_cover = dl.path.relative_to(root).as_posix()
                existing_art = (
                    await session.execute(
                        select(Artwork).where(
                            Artwork.item_id == alb_item.id,
                            Artwork.type == ArtworkType.COVER.value,
                        )
                    )
                ).scalar_one_or_none()
                if existing_art is None:
                    session.add(
                        Artwork(
                            item_id=alb_item.id,
                            type=ArtworkType.COVER.value,
                            rel_path=rel_cover,
                            source_url=arts[0].url,
                            width=dl.width,
                            height=dl.height,
                        )
                    )
                else:
                    existing_art.rel_path = rel_cover
                    existing_art.source_url = arts[0].url
                    existing_art.width = dl.width
                    existing_art.height = dl.height
                has_cover = True
            except ArtworkDownloadError:
                pass

        alb_item.state = ItemState.COMPLETE.value if has_cover else ItemState.MATCHED.value
        matched_count += 1

    await session.commit()
    return matched_count
