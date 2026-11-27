"""TMDB v3 API provider for movies."""

from typing import Any

import httpx

from metashelf.domain.models import ActorCredit, ArtworkType, MovieMetadata
from metashelf.providers.base import (
    ArtworkCandidate,
    Candidate,
    MissingApiKeyError,
    ProviderError,
    SearchQuery,
)
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.rate_limit import AsyncRateLimiter

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"


def _extract_year(release_date: str | None) -> int | None:
    if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


def _extract_certification(release_dates_data: dict[str, Any], lang: str = "en-US") -> str:
    """Extract MPAA/content certification from TMDB release_dates payload."""
    results = release_dates_data.get("results")
    if not isinstance(results, list):
        return ""

    preferred_country = lang.split("-")[1].upper() if "-" in lang else "US"

    def _pick_from_country(country_code: str) -> str:
        for entry in results:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("iso_3166_1") or "").upper() != country_code:
                continue
            dates = entry.get("release_dates")
            if not isinstance(dates, list):
                continue
            # Prefer theatrical (type 3 or 2), then any non-empty certification
            for release_type in (3, 2, None):
                for rd in dates:
                    if not isinstance(rd, dict):
                        continue
                    if release_type is not None and rd.get("type") != release_type:
                        continue
                    cert = str(rd.get("certification") or "").strip()
                    if cert:
                        return cert
        return ""

    for code in (preferred_country, "US"):
        cert = _pick_from_country(code)
        if cert:
            return cert

    for entry in results:
        if isinstance(entry, dict):
            code = str(entry.get("iso_3166_1") or "").upper()
            if code:
                cert = _pick_from_country(code)
                if cert:
                    return cert
    return ""


class TMDBProvider:
    """The Movie Database (TMDB) v3 async provider."""

    id = "tmdb"
    media_kinds = {"movie"}
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
            raise MissingApiKeyError(
                "TMDB API key is not configured. Set METASHELF_TMDB_API_KEY or add it in Settings."
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
        full_params = {"api_key": key, **params}
        url = f"{TMDB_API_BASE}{path}"

        last_exc: Exception | None = None
        for _ in range(3):
            try:
                resp = await self._http.get(url, params=full_params, timeout=15.0)
                if resp.status_code == 401:
                    raise ProviderError("TMDB API key was rejected (HTTP 401).")
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise ProviderError(f"Unexpected TMDB response type for {path}")
                if self._cache is not None:
                    await self._cache.set(cache_key, data)
                return data
            except httpx.HTTPError as exc:
                last_exc = exc
        raise ProviderError(f"TMDB request failed for {path}: {last_exc}")

    async def search(self, kind: str, query: SearchQuery) -> list[Candidate]:
        if kind != "movie":
            return []
        params: dict[str, str] = {
            "query": query.title,
            "language": query.lang,
            "include_adult": "false",
        }
        if query.year is not None:
            params["year"] = str(query.year)

        cache_key = f"tmdb:search:movie:{query.title.lower()}:{query.year or ''}:{query.lang}"
        data = await self._get_json("/search/movie", params, cache_key)
        candidates: list[Candidate] = []
        for raw in data.get("results", []):
            if not isinstance(raw, dict) or "id" not in raw:
                continue
            poster_path = raw.get("poster_path")
            backdrop_path = raw.get("backdrop_path")
            candidates.append(
                Candidate(
                    provider=self.id,
                    provider_id=str(raw["id"]),
                    title=str(raw.get("title") or ""),
                    original_title=str(raw.get("original_title") or ""),
                    year=_extract_year(raw.get("release_date")),
                    overview=str(raw.get("overview") or ""),
                    poster_url=f"{TMDB_IMAGE_BASE}/w342{poster_path}" if poster_path else None,
                    backdrop_url=(
                        f"{TMDB_IMAGE_BASE}/w780{backdrop_path}" if backdrop_path else None
                    ),
                    popularity=float(raw.get("popularity") or 0.0),
                )
            )
        return candidates

    async def fetch(self, kind: str, provider_id: str, lang: str = "en-US") -> MovieMetadata:
        if kind != "movie":
            raise ProviderError(f"Unsupported kind '{kind}' for TMDB movie fetch")
        cache_key = f"tmdb:movie:{provider_id}:{lang}"
        data = await self._get_json(
            f"/movie/{provider_id}",
            {"language": lang, "append_to_response": "credits,release_dates"},
            cache_key,
        )

        release_date = str(data.get("release_date") or "")
        credits_data = data.get("credits") or {}
        cast_raw = credits_data.get("cast", [])
        crew_raw = credits_data.get("crew", [])

        actors: list[ActorCredit] = []
        for idx, member in enumerate(cast_raw[:25]):
            if not isinstance(member, dict) or not member.get("name"):
                continue
            profile = member.get("profile_path")
            actors.append(
                ActorCredit(
                    name=str(member["name"]),
                    role=str(member.get("character") or ""),
                    order=member.get("order") if isinstance(member.get("order"), int) else idx,
                    thumb=f"{TMDB_IMAGE_BASE}/w185{profile}" if profile else "",
                )
            )

        directors: list[str] = []
        writers: list[str] = []
        for crew in crew_raw:
            if not isinstance(crew, dict) or not crew.get("name"):
                continue
            job = str(crew.get("job") or "")
            name = str(crew["name"])
            if job == "Director" and name not in directors:
                directors.append(name)
            elif job in {"Writer", "Screenplay", "Story"} and name not in writers:
                writers.append(name)

        collection_data = data.get("belongs_to_collection")
        collection_name = (
            str(collection_data.get("name") or "")
            if isinstance(collection_data, dict)
            else ""
        )

        overview = str(data.get("overview") or "")
        mpaa = _extract_certification(data.get("release_dates") or {}, lang=lang)
        return MovieMetadata(
            title=str(data.get("title") or ""),
            original_title=str(data.get("original_title") or ""),
            sort_title=str(data.get("title") or ""),
            year=_extract_year(release_date),
            premiered=release_date,
            tagline=str(data.get("tagline") or ""),
            plot=overview,
            outline=overview,
            runtime=data.get("runtime") if isinstance(data.get("runtime"), int) else None,
            mpaa=mpaa,
            rating=(
                round(float(data["vote_average"]), 2)
                if data.get("vote_average") is not None
                else None
            ),
            votes=data.get("vote_count") if isinstance(data.get("vote_count"), int) else None,
            imdb_id=str(data.get("imdb_id") or ""),
            tmdb_id=str(data.get("id") or provider_id),
            genres=[
                str(g["name"])
                for g in data.get("genres", [])
                if isinstance(g, dict) and g.get("name")
            ],
            studios=[
                str(s["name"])
                for s in data.get("production_companies", [])
                if isinstance(s, dict) and s.get("name")
            ],
            countries=[
                str(c["name"])
                for c in data.get("production_countries", [])
                if isinstance(c, dict) and c.get("name")
            ],
            directors=directors,
            writers=writers,
            actors=actors,
            collection=collection_name,
        )

    async def artwork(self, kind: str, provider_id: str) -> list[ArtworkCandidate]:
        if kind != "movie":
            return []
        cache_key = f"tmdb:movie:{provider_id}:images"
        data = await self._get_json(
            f"/movie/{provider_id}/images",
            {"include_image_language": "en,null"},
            cache_key,
        )
        results: list[ArtworkCandidate] = []
        for p in data.get("posters", [])[:12]:
            if isinstance(p, dict) and p.get("file_path"):
                fp = str(p["file_path"])
                results.append(
                    ArtworkCandidate(
                        type=ArtworkType.POSTER.value,
                        url=f"{TMDB_IMAGE_BASE}/original{fp}",
                        thumb_url=f"{TMDB_IMAGE_BASE}/w342{fp}",
                        width=p.get("width"),
                        height=p.get("height"),
                        language=p.get("iso_639_1"),
                        rating=float(p.get("vote_average") or 0.0),
                    )
                )
        for b in data.get("backdrops", [])[:12]:
            if isinstance(b, dict) and b.get("file_path"):
                fp = str(b["file_path"])
                results.append(
                    ArtworkCandidate(
                        type=ArtworkType.FANART.value,
                        url=f"{TMDB_IMAGE_BASE}/original{fp}",
                        thumb_url=f"{TMDB_IMAGE_BASE}/w780{fp}",
                        width=b.get("width"),
                        height=b.get("height"),
                        language=b.get("iso_639_1"),
                        rating=float(b.get("vote_average") or 0.0),
                    )
                )
        return results
