"""Open Library API provider for ebooks."""

from typing import Any

import httpx

from metashelf import __version__
from metashelf.domain.models import ArtworkType, EbookMetadata, NormalizedMetadata
from metashelf.providers.base import (
    ArtworkCandidate,
    Candidate,
    ProviderError,
    SearchQuery,
)
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.rate_limit import AsyncRateLimiter

OL_BASE = "https://openlibrary.org"
OL_COVERS_BASE = "https://covers.openlibrary.org/b"
OL_USER_AGENT = f"MetaShelf/{__version__} (https://github.com/syfq91/MetaShelf)"


def _extract_year(raw: str | None) -> int | None:
    if not raw:
        return None
    for token in raw.split():
        if len(token) >= 4 and token[:4].isdigit():
            return int(token[:4])
    return None


class OpenLibraryProvider:
    """Open Library async provider (no API key required)."""

    id = "openlibrary"
    media_kinds = {"ebook"}
    needs_api_key = False

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        cache: ProviderResponseCache | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ) -> None:
        self._http = http_client
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
        resp = await self._http.get(
            f"{OL_BASE}{path}",
            params=params,
            headers={"User-Agent": OL_USER_AGENT},
            follow_redirects=True,
            timeout=15.0,
        )
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ProviderError(f"Unexpected Open Library response for {path}")
        if self._cache is not None:
            await self._cache.set(cache_key, data)
        return data

    async def search(self, kind: str, query: SearchQuery) -> list[Candidate]:
        if kind != "ebook":
            return []

        params: dict[str, str] = {
            "fields": "key,title,author_name,first_publish_year,publisher,isbn,subject,cover_i",
            "limit": "10",
        }
        if query.isbn:
            params["isbn"] = query.isbn
            cache_key = f"ol:search:isbn:{query.isbn}"
        else:
            params["title"] = query.title
            if query.author:
                params["author"] = query.author
            cache_key = f"ol:search:{query.title.lower()}:{(query.author or '').lower()}"

        data = await self._get_json("/search.json", params, cache_key)
        candidates: list[Candidate] = []
        for doc in data.get("docs", []):
            if not isinstance(doc, dict):
                continue
            isbns = [str(i) for i in doc.get("isbn", []) if i]
            chosen_isbn = query.isbn if query.isbn and query.isbn in isbns else (
                isbns[0] if isbns else ""
            )
            work_key = str(doc.get("key") or "")
            provider_id = chosen_isbn or work_key.lstrip("/")
            if not provider_id:
                continue

            authors = [str(a) for a in doc.get("author_name", []) if a]
            cover_i = doc.get("cover_i")
            poster_url = (
                f"{OL_COVERS_BASE}/id/{cover_i}-M.jpg?default=false"
                if cover_i
                else (
                    f"{OL_COVERS_BASE}/isbn/{chosen_isbn}-M.jpg?default=false"
                    if chosen_isbn
                    else None
                )
            )
            candidates.append(
                Candidate(
                    provider=self.id,
                    provider_id=provider_id,
                    title=str(doc.get("title") or ""),
                    year=doc.get("first_publish_year"),
                    overview=", ".join(authors),
                    poster_url=poster_url,
                    extra={
                        "isbn": chosen_isbn,
                        "authors": "|".join(authors),
                        "work_key": work_key,
                    },
                )
            )
        return candidates

    async def fetch(self, kind: str, provider_id: str, lang: str = "en") -> NormalizedMetadata:
        if kind != "ebook":
            raise ProviderError(f"Unsupported kind '{kind}' for Open Library")

        # If provider_id looks like an ISBN, fetch /isbn/{isbn}.json then its work
        is_isbn = provider_id.replace("-", "").isdigit() or (
            len(provider_id) == 10 and provider_id[:-1].isdigit()
        )
        edition: dict[str, Any] = {}
        work_key = ""
        if is_isbn:
            edition = await self._get_json(
                f"/isbn/{provider_id}.json", None, f"ol:isbn:{provider_id}"
            )
            works = edition.get("works") or []
            if works and isinstance(works[0], dict):
                work_key = str(works[0].get("key") or "")
        else:
            work_key = provider_id if provider_id.startswith("/") else f"/{provider_id}"

        work: dict[str, Any] = {}
        if work_key:
            work = await self._get_json(f"{work_key}.json", None, f"ol:work:{work_key}")

        raw_desc = work.get("description") or edition.get("description") or ""
        if isinstance(raw_desc, dict):
            description = str(raw_desc.get("value") or "")
        else:
            description = str(raw_desc)

        publishers = [str(p) for p in edition.get("publishers", []) if p]
        pub_date = str(edition.get("publish_date") or "")
        subjects = [str(s) for s in work.get("subjects", [])[:10] if s]
        isbns = edition.get("isbn_13") or edition.get("isbn_10") or []
        isbn_val = provider_id if is_isbn else (str(isbns[0]) if isbns else "")

        return EbookMetadata(
            title=str(edition.get("title") or work.get("title") or ""),
            isbn=isbn_val,
            publisher=publishers[0] if publishers else "",
            published_date=pub_date,
            year=_extract_year(pub_date),
            language=lang,
            description=description,
            subjects=subjects,
            openlibrary_id=work_key.lstrip("/") or provider_id,
        )

    async def artwork(self, kind: str, provider_id: str) -> list[ArtworkCandidate]:
        if kind != "ebook":
            return []
        is_isbn = provider_id.replace("-", "").isdigit() or (
            len(provider_id) == 10 and provider_id[:-1].isdigit()
        )
        if is_isbn:
            return [
                ArtworkCandidate(
                    type=ArtworkType.COVER.value,
                    url=f"{OL_COVERS_BASE}/isbn/{provider_id}-L.jpg?default=false",
                    thumb_url=f"{OL_COVERS_BASE}/isbn/{provider_id}-M.jpg?default=false",
                )
            ]
        return []
