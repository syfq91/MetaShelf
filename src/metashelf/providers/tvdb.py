"""TheTVDB v4 API provider for TV shows."""

from typing import Any

import httpx

from metashelf.domain.models import ArtworkType, NormalizedMetadata, ShowMetadata
from metashelf.providers.base import (
    ArtworkCandidate,
    Candidate,
    MissingApiKeyError,
    ProviderError,
    SearchQuery,
)
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.rate_limit import AsyncRateLimiter

TVDB_API_BASE = "https://api4.thetvdb.com/v4"


class TheTVDBProvider:
    """TheTVDB v4 async provider."""

    id = "tvdb"
    media_kinds = {"show"}
    needs_api_key = True

    def __init__(
        self,
        api_key: str,
        http_client: httpx.AsyncClient,
        cache: ProviderResponseCache | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._http = http_client
        self._cache = cache
        self._limiter = rate_limiter or AsyncRateLimiter(calls_per_second=3.0)
        self._token: str = ""

    def _require_key(self) -> str:
        if not self._api_key:
            raise MissingApiKeyError("TheTVDB API key is not configured.")
        return self._api_key

    async def _ensure_token(self) -> str:
        if self._token:
            return self._token
        key = self._require_key()
        await self._limiter.acquire()
        resp = await self._http.post(
            f"{TVDB_API_BASE}/login",
            json={"apikey": key},
            timeout=15.0,
        )
        if resp.status_code == 401:
            raise ProviderError("TheTVDB API key was rejected (HTTP 401).")
        resp.raise_for_status()
        data = resp.json()
        token = str((data.get("data") or {}).get("token") or "")
        if not token:
            raise ProviderError("TheTVDB login did not return a token.")
        self._token = token
        return token

    async def _get_json(
        self,
        path: str,
        params: dict[str, str] | None,
        cache_key: str,
    ) -> dict[str, Any]:
        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        token = await self._ensure_token()
        await self._limiter.acquire()
        resp = await self._http.get(
            f"{TVDB_API_BASE}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ProviderError(f"Unexpected TVDB response for {path}")
        if self._cache is not None:
            await self._cache.set(cache_key, data)
        return data

    async def search(self, kind: str, query: SearchQuery) -> list[Candidate]:
        if kind != "show":
            return []
        cache_key = f"tvdb:search:{query.title.lower()}"
        data = await self._get_json(
            "/search",
            {"query": query.title, "type": "series"},
            cache_key,
        )
        candidates: list[Candidate] = []
        for raw in data.get("data", []):
            if not isinstance(raw, dict):
                continue
            pid = str(raw.get("tvdb_id") or raw.get("id") or "")
            if not pid:
                continue
            year_raw = str(raw.get("year") or "")
            year = int(year_raw[:4]) if len(year_raw) >= 4 and year_raw[:4].isdigit() else None
            candidates.append(
                Candidate(
                    provider=self.id,
                    provider_id=pid,
                    title=str(raw.get("name") or ""),
                    year=year,
                    overview=str(raw.get("overview") or ""),
                    poster_url=raw.get("image_url"),
                )
            )
        return candidates

    async def fetch(self, kind: str, provider_id: str, lang: str = "eng") -> NormalizedMetadata:
        if kind != "show":
            raise ProviderError(f"Unsupported kind '{kind}' for TheTVDB")
        cache_key = f"tvdb:series:{provider_id}"
        payload = await self._get_json(f"/series/{provider_id}/extended", None, cache_key)
        raw = payload.get("data") or {}
        first_aired = str(raw.get("firstAired") or "")
        year = int(first_aired[:4]) if len(first_aired) >= 4 and first_aired[:4].isdigit() else None
        status_obj = raw.get("status")
        status_name = (
            str(status_obj.get("name") or "") if isinstance(status_obj, dict) else ""
        )
        genres = [
            str(g["name"])
            for g in raw.get("genres", [])
            if isinstance(g, dict) and g.get("name")
        ]
        return ShowMetadata(
            title=str(raw.get("name") or ""),
            sort_title=str(raw.get("name") or ""),
            year=year,
            premiered=first_aired,
            status=status_name,
            plot=str(raw.get("overview") or ""),
            outline=str(raw.get("overview") or ""),
            tvdb_id=str(raw.get("id") or provider_id),
            genres=genres,
        )

    async def artwork(self, kind: str, provider_id: str) -> list[ArtworkCandidate]:
        if kind != "show":
            return []
        cache_key = f"tvdb:series:{provider_id}"
        payload = await self._get_json(f"/series/{provider_id}/extended", None, cache_key)
        raw = payload.get("data") or {}
        image = raw.get("image")
        if image:
            return [ArtworkCandidate(type=ArtworkType.POSTER.value, url=str(image))]
        return []
