"""OpenSubtitles REST API v1 provider and 64-bit movie hash calculator."""

import struct
from pathlib import Path
from typing import Any

import httpx

from metashelf import __version__
from metashelf.providers.base import (
    MissingApiKeyError,
    ProviderError,
    QuotaExceededError,
    SubtitleCandidate,
    SubtitleDownload,
    SubtitleQuery,
)
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.rate_limit import AsyncRateLimiter

OS_API_BASE = "https://api.opensubtitles.com/api/v1"
OS_USER_AGENT = f"MetaShelf v{__version__}"
_HASH_CHUNK = 65536


def compute_opensubtitles_hash(path: Path) -> str | None:
    """Compute the standard OpenSubtitles 64-bit hash for a video file."""
    if not path.is_file():
        return None
    size = path.stat().st_size
    if size < _HASH_CHUNK * 2:
        return None

    longlong_fmt = "<Q"
    byte_size = struct.calcsize(longlong_fmt)
    total = size

    with path.open("rb") as f:
        for _ in range(_HASH_CHUNK // byte_size):
            (val,) = struct.unpack(longlong_fmt, f.read(byte_size))
            total = (total + val) & 0xFFFFFFFFFFFFFFFF
        f.seek(max(0, size - _HASH_CHUNK), 0)
        for _ in range(_HASH_CHUNK // byte_size):
            (val,) = struct.unpack(longlong_fmt, f.read(byte_size))
            total = (total + val) & 0xFFFFFFFFFFFFFFFF

    return f"{total:016x}"


class OpenSubtitlesProvider:
    """OpenSubtitles REST API v1 async subtitle provider."""

    id = "opensubtitles"
    needs_api_key = True

    def __init__(
        self,
        api_key: str,
        http_client: httpx.AsyncClient,
        username: str = "",
        password: str = "",
        cache: ProviderResponseCache | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._username = username.strip()
        self._password = password
        self._http = http_client
        self._cache = cache
        self._limiter = rate_limiter or AsyncRateLimiter(calls_per_second=2.0)
        self._token: str = ""

    def _require_key(self) -> str:
        if not self._api_key:
            raise MissingApiKeyError(
                "OpenSubtitles API key is not configured. Set METASHELF_OPENSUBTITLES_API_KEY."
            )
        return self._api_key

    def _headers(self, include_auth: bool = False) -> dict[str, str]:
        headers = {
            "Api-Key": self._require_key(),
            "User-Agent": OS_USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if include_auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _ensure_token(self) -> str:
        if self._token:
            return self._token
        if not self._username or not self._password:
            raise ProviderError("OpenSubtitles username and password are required to download.")
        await self._limiter.acquire()
        resp = await self._http.post(
            f"{OS_API_BASE}/login",
            headers=self._headers(),
            json={"username": self._username, "password": self._password},
            timeout=15.0,
        )
        if resp.status_code == 401:
            raise ProviderError("OpenSubtitles login failed (HTTP 401).")
        resp.raise_for_status()
        data = resp.json()
        token = str(data.get("token") or "")
        if not token:
            raise ProviderError("OpenSubtitles login did not return a token.")
        self._token = token
        return token

    async def _search_params(self, params: dict[str, str]) -> list[SubtitleCandidate]:
        cache_key = "os:search:" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        data: dict[str, Any] | None = None
        if self._cache is not None:
            data = await self._cache.get(cache_key)

        if data is None:
            await self._limiter.acquire()
            resp = await self._http.get(
                f"{OS_API_BASE}/subtitles",
                params=params,
                headers=self._headers(),
                timeout=15.0,
            )
            if resp.status_code == 429:
                raise QuotaExceededError("OpenSubtitles rate limit exceeded (HTTP 429).")
            resp.raise_for_status()
            parsed = resp.json()
            if not isinstance(parsed, dict):
                return []
            data = parsed
            if self._cache is not None:
                await self._cache.set(cache_key, data)

        candidates: list[SubtitleCandidate] = []
        for entry in data.get("data", []):
            if not isinstance(entry, dict):
                continue
            attrs = entry.get("attributes") or {}
            files = attrs.get("files") or []
            if not files or not isinstance(files[0], dict):
                continue
            file_id = str(files[0].get("file_id") or "")
            if not file_id:
                continue
            hash_match = bool(attrs.get("moviehash_match"))
            rating = float(attrs.get("ratings") or 0.0)
            score = (1.0 if hash_match else 0.7) + min(rating / 100.0, 0.09)
            candidates.append(
                SubtitleCandidate(
                    provider=self.id,
                    provider_id=str(entry.get("id") or file_id),
                    file_id=file_id,
                    lang=str(attrs.get("language") or "en"),
                    format="srt",
                    forced=bool(attrs.get("foreign_parts_only")),
                    hearing_impaired=bool(attrs.get("hearing_impaired")),
                    synced=hash_match,
                    score=round(score, 4),
                    release_name=str(files[0].get("file_name") or ""),
                )
            )
        return candidates

    async def search(self, query: SubtitleQuery) -> list[SubtitleCandidate]:
        """Search OpenSubtitles: file hash first, then ID + S/E, then title + year."""
        self._require_key()
        langs = ",".join(query.languages or ["en"])

        # 1. File hash first
        if query.movie_hash:
            cands = await self._search_params(
                {"moviehash": query.movie_hash, "languages": langs}
            )
            if cands:
                return cands

        # 2. Provider / IMDb / TMDB ID (+ season & episode)
        id_params: dict[str, str] = {"languages": langs}
        if query.tmdb_id:
            id_params["tmdb_id"] = query.tmdb_id
        elif query.imdb_id:
            id_params["imdb_id"] = query.imdb_id.lstrip("t")
        if len(id_params) > 1:
            if query.season is not None:
                id_params["season_number"] = str(query.season)
            if query.episode is not None:
                id_params["episode_number"] = str(query.episode)
            cands = await self._search_params(id_params)
            if cands:
                return cands

        # 3. Title + year fallback
        if query.title:
            title_params: dict[str, str] = {"query": query.title, "languages": langs}
            if query.year is not None:
                title_params["year"] = str(query.year)
            if query.season is not None:
                title_params["season_number"] = str(query.season)
            if query.episode is not None:
                title_params["episode_number"] = str(query.episode)
            return await self._search_params(title_params)
        return []

    async def download(self, candidate: SubtitleCandidate) -> SubtitleDownload:
        """Download subtitle bytes via OpenSubtitles /download endpoint."""
        await self._ensure_token()
        await self._limiter.acquire()
        resp = await self._http.post(
            f"{OS_API_BASE}/download",
            headers=self._headers(include_auth=True),
            json={"file_id": int(candidate.file_id)},
            timeout=20.0,
        )
        if resp.status_code in {406, 429}:
            raise QuotaExceededError("OpenSubtitles daily download quota exceeded.")
        resp.raise_for_status()
        data = resp.json()
        remaining = data.get("remaining")
        if remaining is not None and int(remaining) < 0:
            raise QuotaExceededError("OpenSubtitles daily download quota exceeded.")

        link = str(data.get("link") or "")
        if not link:
            raise ProviderError("OpenSubtitles /download did not return a download link.")

        file_resp = await self._http.get(link, timeout=30.0)
        file_resp.raise_for_status()
        return SubtitleDownload(
            content=file_resp.content,
            file_name=str(data.get("file_name") or candidate.release_name),
            remaining_quota=int(remaining) if remaining is not None else None,
        )
