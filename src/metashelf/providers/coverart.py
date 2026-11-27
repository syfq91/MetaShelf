"""Cover Art Archive API provider."""

import httpx

from metashelf.domain.models import AlbumMetadata, ArtworkType, NormalizedMetadata
from metashelf.providers.base import ArtworkCandidate, Candidate, SearchQuery
from metashelf.providers.cache import ProviderResponseCache

CAA_BASE = "https://coverartarchive.org"


class CoverArtArchiveProvider:
    """Cover Art Archive async artwork provider (no API key)."""

    id = "coverart"
    media_kinds = {"album"}
    needs_api_key = False

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        cache: ProviderResponseCache | None = None,
    ) -> None:
        self._http = http_client
        self._cache = cache

    async def search(self, _kind: str, _query: SearchQuery) -> list[Candidate]:
        return []

    async def fetch(self, _kind: str, _provider_id: str, _lang: str = "en") -> NormalizedMetadata:
        return AlbumMetadata()

    async def artwork(
        self,
        kind: str,
        provider_id: str,
        release_group_id: str = "",
    ) -> list[ArtworkCandidate]:
        """Fetch cover art candidates for a MusicBrainz release (or release-group fallback)."""
        if kind != "album":
            return []

        for endpoint in (
            f"/release/{provider_id}",
            f"/release-group/{release_group_id}" if release_group_id else "",
        ):
            if not endpoint:
                continue
            cache_key = f"caa:{endpoint}"
            data = await self._cache.get(cache_key) if self._cache else None
            if data is None:
                resp = await self._http.get(
                    f"{CAA_BASE}{endpoint}",
                    follow_redirects=True,
                    timeout=15.0,
                )
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                parsed = resp.json()
                if not isinstance(parsed, dict):
                    continue
                data = parsed
                if self._cache is not None:
                    await self._cache.set(cache_key, data)

            results: list[ArtworkCandidate] = []
            for img in data.get("images", []):
                if not isinstance(img, dict) or not img.get("image"):
                    continue
                is_front = bool(img.get("front")) or "Front" in (img.get("types") or [])
                if not is_front:
                    continue
                thumbs = img.get("thumbnails") or {}
                thumb_url = thumbs.get("500") or thumbs.get("250") or img.get("image")
                results.append(
                    ArtworkCandidate(
                        type=ArtworkType.COVER.value,
                        url=str(img["image"]).replace("http://", "https://"),
                        thumb_url=str(thumb_url).replace("http://", "https://")
                        if thumb_url
                        else None,
                    )
                )
            if results:
                return results
        return []
