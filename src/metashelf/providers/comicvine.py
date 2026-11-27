"""Comic Vine API provider for comics."""

import re
from dataclasses import dataclass
from typing import Any

import httpx

from metashelf import __version__
from metashelf.domain.models import ArtworkType, ComicMetadata, NormalizedMetadata
from metashelf.providers.base import (
    ArtworkCandidate,
    Candidate,
    MissingApiKeyError,
    ProviderError,
    SearchQuery,
)
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.rate_limit import AsyncRateLimiter

COMICVINE_API_BASE = "https://comicvine.gamespot.com/api"
COMICVINE_USER_AGENT = f"MetaShelf/{__version__} (https://github.com/syfq91/MetaShelf)"
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    return " ".join(_HTML_TAG_RE.sub(" ", raw).split())


def _parse_date_parts(cover_date: str | None) -> tuple[int | None, int | None, int | None]:
    if not cover_date:
        return None, None, None
    parts = cover_date.split("-")
    year = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else None
    month = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
    day = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else None
    return year, month, day


@dataclass
class VolumeIssueSummary:
    """Lightweight issue reference returned by Comic Vine /issues/."""

    issue_id: str
    number: str
    title: str
    cover_date: str = ""


class ComicVineProvider:
    """Comic Vine async provider (API key required, strict rate limit)."""

    id = "comicvine"
    media_kinds = {"comic"}
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
        self._limiter = rate_limiter or AsyncRateLimiter(calls_per_second=0.8)

    def _require_key(self) -> str:
        if not self._api_key:
            raise MissingApiKeyError(
                "Comic Vine API key is not configured. Set METASHELF_COMICVINE_API_KEY."
            )
        return self._api_key

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

        key = self._require_key()
        await self._limiter.acquire()
        full_params = {"api_key": key, "format": "json", **params}
        resp = await self._http.get(
            f"{COMICVINE_API_BASE}{path}",
            params=full_params,
            headers={"User-Agent": COMICVINE_USER_AGENT},
            timeout=20.0,
        )
        if resp.status_code == 429:
            raise ProviderError("Comic Vine rate limit exceeded (HTTP 429).")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ProviderError(f"Unexpected Comic Vine response for {path}")
        status_code = data.get("status_code")
        if status_code == 107:
            raise ProviderError("Comic Vine rate limit exceeded (status_code 107).")
        if status_code != 1:
            raise ProviderError(f"Comic Vine error ({status_code}): {data.get('error')}")
        if self._cache is not None:
            await self._cache.set(cache_key, data)
        return data

    async def search(self, kind: str, query: SearchQuery) -> list[Candidate]:
        """Search Comic Vine volumes by series title."""
        if kind != "comic":
            return []
        cache_key = f"cv:search:volume:{query.title.lower()}"
        data = await self._get_json(
            "/search/",
            {"resources": "volume", "query": query.title},
            cache_key,
        )
        candidates: list[Candidate] = []
        for raw in data.get("results", []):
            if not isinstance(raw, dict) or "id" not in raw:
                continue
            start_year_raw = str(raw.get("start_year") or "")
            year = int(start_year_raw[:4]) if start_year_raw[:4].isdigit() else None
            pub = (raw.get("publisher") or {}).get("name") or ""
            img = (raw.get("image") or {}).get("medium_url")
            candidates.append(
                Candidate(
                    provider=self.id,
                    provider_id=str(raw["id"]),
                    title=str(raw.get("name") or ""),
                    year=year,
                    overview=_strip_html(raw.get("description")),
                    poster_url=str(img) if img else None,
                    extra={
                        "publisher": str(pub),
                        "issue_count": str(raw.get("count_of_issues") or 0),
                    },
                )
            )
        return candidates

    async def list_volume_issues(self, volume_id: str) -> list[VolumeIssueSummary]:
        """List issues belonging to a Comic Vine volume."""
        cache_key = f"cv:volume:{volume_id}:issues"
        data = await self._get_json(
            "/issues/",
            {"filter": f"volume:{volume_id}", "limit": "100"},
            cache_key,
        )
        issues: list[VolumeIssueSummary] = []
        for raw in data.get("results", []):
            if not isinstance(raw, dict) or "id" not in raw:
                continue
            issues.append(
                VolumeIssueSummary(
                    issue_id=str(raw["id"]),
                    number=str(raw.get("issue_number") or ""),
                    title=str(raw.get("name") or ""),
                    cover_date=str(raw.get("cover_date") or ""),
                )
            )
        return issues

    async def fetch(
        self,
        kind: str,
        provider_id: str,
        lang: str = "en",
    ) -> NormalizedMetadata:
        """Fetch full issue metadata by Comic Vine issue ID."""
        if kind != "comic":
            raise ProviderError(f"Unsupported kind '{kind}' for Comic Vine")
        cache_key = f"cv:issue:{provider_id}"
        data = await self._get_json(f"/issue/4000-{provider_id}/", {}, cache_key)
        raw = data.get("results") or {}

        writers: list[str] = []
        pencillers: list[str] = []
        inkers: list[str] = []
        colorists: list[str] = []
        letterers: list[str] = []
        cover_artists: list[str] = []
        editors: list[str] = []

        for person in raw.get("person_credits", []):
            if not isinstance(person, dict) or not person.get("name"):
                continue
            name = str(person["name"])
            roles = {r.strip().lower() for r in str(person.get("role") or "").split(",")}
            if "writer" in roles and name not in writers:
                writers.append(name)
            is_penciller = bool(roles & {"penciler", "penciller", "artist"})
            if is_penciller and name not in pencillers:
                pencillers.append(name)
            if "inker" in roles and name not in inkers:
                inkers.append(name)
            if "colorist" in roles and name not in colorists:
                colorists.append(name)
            if "letterer" in roles and name not in letterers:
                letterers.append(name)
            if "cover" in roles and name not in cover_artists:
                cover_artists.append(name)
            if "editor" in roles and name not in editors:
                editors.append(name)

        artists: list[str] = []
        for name in pencillers + inkers + cover_artists:
            if name not in artists:
                artists.append(name)

        vol = raw.get("volume") or {}
        year, month, day = _parse_date_parts(raw.get("cover_date"))
        return ComicMetadata(
            title=str(raw.get("name") or ""),
            series=str(vol.get("name") or ""),
            number=str(raw.get("issue_number") or ""),
            year=year,
            month=month,
            day=day,
            summary=_strip_html(raw.get("description")),
            writers=writers,
            artists=artists,
            pencillers=pencillers,
            inkers=inkers,
            colorists=colorists,
            letterers=letterers,
            cover_artists=cover_artists,
            editors=editors,
            web=str(raw.get("site_detail_url") or ""),
            comicvine_volume_id=str(vol.get("id") or ""),
            comicvine_issue_id=str(raw.get("id") or provider_id),
        )

    async def artwork(self, kind: str, provider_id: str) -> list[ArtworkCandidate]:
        if kind != "comic":
            return []
        cache_key = f"cv:issue:{provider_id}"
        data = await self._get_json(f"/issue/4000-{provider_id}/", {}, cache_key)
        raw = data.get("results") or {}
        img = raw.get("image") or {}
        url = img.get("super_url") or img.get("medium_url")
        if not url:
            return []
        return [
            ArtworkCandidate(
                type=ArtworkType.COVER.value,
                url=str(url),
                thumb_url=str(img.get("medium_url") or url),
            )
        ]
