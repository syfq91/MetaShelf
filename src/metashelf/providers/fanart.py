"""fanart.tv API v3 provider for extra TV artwork."""

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

FANART_API_BASE = "https://webservice.fanart.tv/v3"


class FanartTVProvider:
    """fanart.tv v3 async artwork provider."""

    id = "fanart"
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

    def _require_key(self) -> str:
        if not self._api_key:
            raise MissingApiKeyError("fanart.tv API key is not configured.")
        return self._api_key

    async def search(self, _kind: str, _query: SearchQuery) -> list[Candidate]:
        return []

    async def fetch(self, _kind: str, _provider_id: str, _lang: str = "en") -> NormalizedMetadata:
        return ShowMetadata()

    async def artwork(self, kind: str, provider_id: str) -> list[ArtworkCandidate]:
        """Fetch TV artwork from fanart.tv using a TheTVDB ID."""
        if kind != "show":
            return []
        key = self._require_key()
        cache_key = f"fanart:tv:{provider_id}"

        data: dict[str, Any] | None = None
        if self._cache is not None:
            data = await self._cache.get(cache_key)

        if data is None:
            await self._limiter.acquire()
            resp = await self._http.get(
                f"{FANART_API_BASE}/tv/{provider_id}",
                headers={"api-key": key},
                timeout=15.0,
            )
            if resp.status_code == 404:
                return []
            if resp.status_code == 401:
                raise ProviderError("fanart.tv API key was rejected (HTTP 401).")
            resp.raise_for_status()
            parsed = resp.json()
            if not isinstance(parsed, dict):
                return []
            data = parsed
            if self._cache is not None:
                await self._cache.set(cache_key, data)

        mapping = [
            ("tvposter", ArtworkType.POSTER.value),
            ("showbackground", ArtworkType.FANART.value),
            ("tvbanner", ArtworkType.BANNER.value),
            ("hdtvlogo", ArtworkType.LOGO.value),
            ("clearlogo", ArtworkType.LOGO.value),
        ]
        results: list[ArtworkCandidate] = []
        for api_field, art_type in mapping:
            for item in data.get(api_field, [])[:6]:
                if isinstance(item, dict) and item.get("url"):
                    results.append(
                        ArtworkCandidate(
                            type=art_type,
                            url=str(item["url"]),
                            language=item.get("lang") or None,
                            rating=float(item.get("likes") or 0.0),
                        )
                    )
        return results
