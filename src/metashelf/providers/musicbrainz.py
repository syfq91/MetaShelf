"""MusicBrainz WS/2 API provider (strict 1 req/sec rate limit + User-Agent)."""

from typing import Any

import httpx

from metashelf import __version__
from metashelf.domain.models import (
    AlbumMetadata,
    ArtistMetadata,
    NormalizedMetadata,
    TrackInfo,
)
from metashelf.providers.base import (
    ArtworkCandidate,
    Candidate,
    ProviderError,
    SearchQuery,
)
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.rate_limit import AsyncRateLimiter

MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
DEFAULT_USER_AGENT = f"MetaShelf/{__version__} (https://github.com/syfq91/MetaShelf)"


def _extract_year(date_str: str | None) -> int | None:
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


class MusicBrainzProvider:
    """MusicBrainz WS/2 async provider (no API key, strict 1 req/sec)."""

    id = "musicbrainz"
    media_kinds = {"artist", "album"}
    needs_api_key = False

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        cache: ProviderResponseCache | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._http = http_client
        self._cache = cache
        self._limiter = rate_limiter or AsyncRateLimiter(calls_per_second=1.0)
        self._user_agent = user_agent

    @property
    def rate_limiter_interval(self) -> float:
        return self._limiter._interval

    async def _get_json(
        self,
        path: str,
        params: dict[str, str],
        cache_key: str,
    ) -> dict[str, Any]:
        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        full_params = {"fmt": "json", **params}
        resp = await self._http.get(
            f"{MUSICBRAINZ_API_BASE}{path}",
            params=full_params,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
            timeout=15.0,
        )
        if resp.status_code == 503:
            raise ProviderError("MusicBrainz rate limit exceeded (HTTP 503).")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ProviderError(f"Unexpected MusicBrainz response for {path}")
        if self._cache is not None:
            await self._cache.set(cache_key, data)
        return data

    async def search(self, kind: str, query: SearchQuery) -> list[Candidate]:
        if kind == "artist":
            return await self._search_artist(query)
        if kind == "album":
            return await self._search_release(query)
        return []

    async def _search_artist(self, query: SearchQuery) -> list[Candidate]:
        cache_key = f"mb:search:artist:{query.title.lower()}"
        data = await self._get_json("/artist", {"query": query.title}, cache_key)
        candidates: list[Candidate] = []
        for raw in data.get("artists", [])[:15]:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            life = raw.get("life-span") or {}
            candidates.append(
                Candidate(
                    provider=self.id,
                    provider_id=str(raw["id"]),
                    title=str(raw.get("name") or ""),
                    year=_extract_year(life.get("begin")),
                    overview=str(raw.get("disambiguation") or ""),
                    popularity=float(raw.get("score") or 0.0),
                )
            )
        return candidates

    async def _search_release(self, query: SearchQuery) -> list[Candidate]:
        cache_key = f"mb:search:release:{query.title.lower()}:{query.year or ''}"
        q_str = query.title
        if query.year is not None:
            q_str = f'release:"{query.title}" AND date:{query.year}*'
        data = await self._get_json("/release", {"query": q_str}, cache_key)
        candidates: list[Candidate] = []
        for raw in data.get("releases", [])[:20]:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            track_count = raw.get("track-count")
            if track_count is None:
                media = raw.get("media") or []
                track_count = sum(
                    int(m.get("track-count") or 0) for m in media if isinstance(m, dict)
                )
            artist_credits = raw.get("artist-credit") or []
            artist_name = ""
            if artist_credits and isinstance(artist_credits[0], dict):
                artist_name = str(artist_credits[0].get("name") or "")

            candidates.append(
                Candidate(
                    provider=self.id,
                    provider_id=str(raw["id"]),
                    title=str(raw.get("title") or ""),
                    year=_extract_year(raw.get("date")),
                    overview=f"{artist_name} ({raw.get('country') or ''})".strip(),
                    extra={
                        "track_count": str(track_count or 0),
                        "artist": artist_name,
                        "release_group_id": str((raw.get("release-group") or {}).get("id") or ""),
                    },
                )
            )
        return candidates

    async def fetch(
        self,
        kind: str,
        provider_id: str,
        lang: str = "en",
    ) -> NormalizedMetadata:
        if kind == "artist":
            return await self._fetch_artist(provider_id)
        if kind == "album":
            return await self._fetch_album(provider_id)
        raise ProviderError(f"Unsupported kind '{kind}' for MusicBrainz")

    async def _fetch_artist(self, mbid: str) -> ArtistMetadata:
        cache_key = f"mb:artist:{mbid}"
        data = await self._get_json(
            f"/artist/{mbid}",
            {"inc": "tags"},
            cache_key,
        )
        life = data.get("life-span") or {}
        tags = [
            str(t["name"])
            for t in data.get("tags", [])
            if isinstance(t, dict) and t.get("name")
        ]
        return ArtistMetadata(
            name=str(data.get("name") or ""),
            sort_name=str(data.get("sort-name") or data.get("name") or ""),
            musicbrainz_artist_id=str(data.get("id") or mbid),
            artist_type=str(data.get("type") or ""),
            gender=str(data.get("gender") or ""),
            disambiguation=str(data.get("disambiguation") or ""),
            formed=str(life.get("begin") or ""),
            disbanded=str(life.get("end") or ""),
            genres=tags[:10],
        )

    async def _fetch_album(self, mbid: str) -> AlbumMetadata:
        cache_key = f"mb:release:{mbid}"
        data = await self._get_json(
            f"/release/{mbid}",
            {"inc": "recordings+artists+release-groups+labels+tags"},
            cache_key,
        )
        rg = data.get("release-group") or {}
        credits_raw = data.get("artist-credit") or []
        artist_name = ""
        artist_mbid = ""
        if credits_raw and isinstance(credits_raw[0], dict):
            artist_name = str(credits_raw[0].get("name") or "")
            artist_obj = credits_raw[0].get("artist") or {}
            if isinstance(artist_obj, dict):
                artist_mbid = str(artist_obj.get("id") or "")

        labels_raw = data.get("label-info") or []
        label_name = ""
        if labels_raw and isinstance(labels_raw[0], dict):
            lbl = labels_raw[0].get("label") or {}
            if isinstance(lbl, dict):
                label_name = str(lbl.get("name") or "")

        tracks: list[TrackInfo] = []
        for medium in data.get("media", []):
            if not isinstance(medium, dict):
                continue
            disc_num = int(medium.get("position") or 1)
            for t in medium.get("tracks", []):
                if not isinstance(t, dict):
                    continue
                tracks.append(
                    TrackInfo(
                        position=int(t.get("position") or len(tracks) + 1),
                        disc=disc_num,
                        title=str(t.get("title") or ""),
                        duration_ms=t.get("length") if isinstance(t.get("length"), int) else None,
                    )
                )

        release_date = str(data.get("date") or "")
        tags = [
            str(t["name"])
            for t in data.get("tags", [])
            if isinstance(t, dict) and t.get("name")
        ]
        return AlbumMetadata(
            title=str(data.get("title") or ""),
            artist=artist_name,
            musicbrainz_artist_id=artist_mbid,
            musicbrainz_album_id=str(data.get("id") or mbid),
            musicbrainz_release_group_id=str(rg.get("id") or ""),
            year=_extract_year(release_date),
            release_date=release_date,
            label=label_name,
            release_type=str(rg.get("primary-type") or "Album"),
            genres=tags[:10],
            tracks=tracks,
        )

    async def artwork(self, _kind: str, _provider_id: str) -> list[ArtworkCandidate]:
        return []
