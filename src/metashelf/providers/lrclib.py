"""LRCLIB API provider for synced (.lrc) and plain (.txt) track lyrics."""

from typing import Any

import httpx

from metashelf import __version__
from metashelf.providers.base import LyricsCandidate, LyricsQuery
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.rate_limit import AsyncRateLimiter

LRCLIB_API_BASE = "https://lrclib.net/api"
LRCLIB_USER_AGENT = f"MetaShelf/{__version__} (https://github.com/syfq91/MetaShelf)"


def _records_to_candidates(records: list[dict[str, Any]]) -> list[LyricsCandidate]:
    candidates: list[LyricsCandidate] = []
    for rec in records:
        if not isinstance(rec, dict) or rec.get("instrumental"):
            continue
        rec_id = str(rec.get("id") or "")
        synced_text = rec.get("syncedLyrics")
        plain_text = rec.get("plainLyrics")
        if isinstance(synced_text, str) and synced_text.strip():
            candidates.append(
                LyricsCandidate(
                    provider="lrclib",
                    provider_id=rec_id,
                    lang="en",
                    format="lrc",
                    synced=True,
                    score=1.0,
                    text=synced_text,
                )
            )
        if isinstance(plain_text, str) and plain_text.strip():
            candidates.append(
                LyricsCandidate(
                    provider="lrclib",
                    provider_id=rec_id,
                    lang="en",
                    format="txt",
                    synced=False,
                    score=0.8,
                    text=plain_text,
                )
            )
    candidates.sort(key=lambda c: (c.synced, c.score), reverse=True)
    return candidates


class LRCLIBProvider:
    """LRCLIB async lyrics provider (no API key required)."""

    id = "lrclib"
    needs_api_key = False

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        cache: ProviderResponseCache | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ) -> None:
        self._http = http_client
        self._cache = cache
        self._limiter = rate_limiter or AsyncRateLimiter(calls_per_second=3.0)

    async def search(self, query: LyricsQuery) -> list[LyricsCandidate]:
        """Query LRCLIB /api/get first (with duration), then fallback to /api/search."""
        params: dict[str, str] = {
            "artist_name": query.artist,
            "track_name": query.title,
        }
        if query.album:
            params["album_name"] = query.album
        if query.duration_seconds is not None and 1 <= query.duration_seconds <= 3600:
            params["duration"] = str(query.duration_seconds)

        cache_key = (
            f"lrclib:get:{query.artist.lower()}:{query.title.lower()}"
            f":{query.album.lower()}:{query.duration_seconds or ''}"
        )
        cached = await self._cache.get(cache_key) if self._cache else None
        if cached is not None and isinstance(cached.get("records"), list):
            return _records_to_candidates(cached["records"])

        await self._limiter.acquire()
        resp = await self._http.get(
            f"{LRCLIB_API_BASE}/get",
            params=params,
            headers={"User-Agent": LRCLIB_USER_AGENT},
            timeout=15.0,
        )
        records: list[dict[str, Any]] = []
        if resp.status_code == 200:
            payload = resp.json()
            if isinstance(payload, dict):
                records = [payload]
        elif resp.status_code == 404:
            await self._limiter.acquire()
            s_params = {"track_name": query.title, "artist_name": query.artist}
            s_resp = await self._http.get(
                f"{LRCLIB_API_BASE}/search",
                params=s_params,
                headers={"User-Agent": LRCLIB_USER_AGENT},
                timeout=15.0,
            )
            if s_resp.status_code == 200:
                s_payload = s_resp.json()
                if isinstance(s_payload, list):
                    records = [r for r in s_payload if isinstance(r, dict)]
        else:
            resp.raise_for_status()

        if self._cache is not None and records:
            await self._cache.set(cache_key, {"records": records})
        return _records_to_candidates(records)
