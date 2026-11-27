"""Google Books API v1 provider for ebooks."""

from typing import Any

import httpx

from metashelf.domain.models import ArtworkType, EbookMetadata, NormalizedMetadata
from metashelf.providers.base import (
    ArtworkCandidate,
    Candidate,
    ProviderError,
    SearchQuery,
)
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.rate_limit import AsyncRateLimiter

GB_API_BASE = "https://www.googleapis.com/books/v1"


def _extract_year(raw: str | None) -> int | None:
    if raw and len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return None


def _extract_isbn(identifiers: list[dict[str, Any]]) -> str:
    isbn13 = ""
    isbn10 = ""
    for item in identifiers:
        if not isinstance(item, dict):
            continue
        t = str(item.get("type") or "")
        val = str(item.get("identifier") or "")
        if t == "ISBN_13" and val:
            isbn13 = val
        elif t == "ISBN_10" and val:
            isbn10 = val
    return isbn13 or isbn10


class GoogleBooksProvider:
    """Google Books v1 async provider (optional API key)."""

    id = "googlebooks"
    media_kinds = {"ebook"}
    needs_api_key = False

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        api_key: str = "",
        cache: ProviderResponseCache | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ) -> None:
        self._http = http_client
        self._api_key = api_key.strip()
        self._cache = cache
        self._limiter = rate_limiter or AsyncRateLimiter(calls_per_second=2.0)

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

        await self._limiter.acquire()
        full_params = dict(params or {})
        if self._api_key:
            full_params["key"] = self._api_key

        resp = await self._http.get(
            f"{GB_API_BASE}{path}",
            params=full_params,
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ProviderError(f"Unexpected Google Books response for {path}")
        if self._cache is not None:
            await self._cache.set(cache_key, data)
        return data

    async def search(self, kind: str, query: SearchQuery) -> list[Candidate]:
        if kind != "ebook":
            return []
        if query.isbn:
            q_str = f"isbn:{query.isbn}"
        else:
            parts = [f"intitle:{query.title}"]
            if query.author:
                parts.append(f"inauthor:{query.author}")
            q_str = "+".join(parts)

        cache_key = f"gb:search:{q_str.lower()}"
        data = await self._get_json("/volumes", {"q": q_str, "maxResults": "10"}, cache_key)
        candidates: list[Candidate] = []
        for item in data.get("items", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            info = item.get("volumeInfo") or {}
            links = info.get("imageLinks") or {}
            thumb = links.get("thumbnail") or links.get("smallThumbnail")
            if isinstance(thumb, str):
                thumb = thumb.replace("http://", "https://")
            authors = [str(a) for a in info.get("authors", []) if a]
            isbn = _extract_isbn(info.get("industryIdentifiers") or [])
            candidates.append(
                Candidate(
                    provider=self.id,
                    provider_id=str(item["id"]),
                    title=str(info.get("title") or ""),
                    year=_extract_year(info.get("publishedDate")),
                    overview=str(info.get("description") or ""),
                    poster_url=thumb,
                    extra={"isbn": isbn, "authors": "|".join(authors)},
                )
            )
        return candidates

    async def fetch(self, kind: str, provider_id: str, lang: str = "en") -> NormalizedMetadata:
        if kind != "ebook":
            raise ProviderError(f"Unsupported kind '{kind}' for Google Books")
        cache_key = f"gb:volume:{provider_id}"
        data = await self._get_json(f"/volumes/{provider_id}", None, cache_key)
        info = data.get("volumeInfo") or {}
        pub_date = str(info.get("publishedDate") or "")
        return EbookMetadata(
            title=str(info.get("title") or ""),
            authors=[str(a) for a in info.get("authors", []) if a],
            isbn=_extract_isbn(info.get("industryIdentifiers") or []),
            publisher=str(info.get("publisher") or ""),
            published_date=pub_date,
            year=_extract_year(pub_date),
            language=str(info.get("language") or lang),
            description=str(info.get("description") or ""),
            subjects=[str(c) for c in info.get("categories", []) if c],
            googlebooks_id=str(data.get("id") or provider_id),
        )

    async def artwork(self, kind: str, provider_id: str) -> list[ArtworkCandidate]:
        if kind != "ebook":
            return []
        cache_key = f"gb:volume:{provider_id}"
        data = await self._get_json(f"/volumes/{provider_id}", None, cache_key)
        info = data.get("volumeInfo") or {}
        links = info.get("imageLinks") or {}
        raw_url = (
            links.get("extraLarge")
            or links.get("large")
            or links.get("medium")
            or links.get("thumbnail")
        )
        if not raw_url:
            return []
        https_url = str(raw_url).replace("http://", "https://")
        return [ArtworkCandidate(type=ArtworkType.COVER.value, url=https_url)]
