"""Provider protocol and shared request/response models."""

from typing import Protocol

from pydantic import BaseModel, Field

from metashelf.domain.models import NormalizedMetadata


class ProviderError(RuntimeError):
    """Base error for metadata providers."""


class MissingApiKeyError(ProviderError):
    """Raised when a provider requires an API key that is not configured."""


class SearchQuery(BaseModel):
    """Normalized search query sent to providers."""

    title: str
    year: int | None = None
    lang: str = "en-US"


class Candidate(BaseModel):
    """A search result candidate returned by a provider."""

    provider: str
    provider_id: str
    title: str
    original_title: str = ""
    year: int | None = None
    overview: str = ""
    poster_url: str | None = None
    backdrop_url: str | None = None
    popularity: float = 0.0
    extra: dict[str, str] = Field(default_factory=dict)


class ArtworkCandidate(BaseModel):
    """An artwork image candidate returned by a provider."""

    type: str  # poster, fanart
    url: str
    thumb_url: str | None = None
    width: int | None = None
    height: int | None = None
    language: str | None = None
    rating: float = 0.0


class Provider(Protocol):
    """Async metadata provider protocol."""

    id: str
    media_kinds: set[str]
    needs_api_key: bool

    async def search(self, kind: str, query: SearchQuery) -> list[Candidate]: ...

    async def fetch(self, kind: str, provider_id: str, lang: str) -> NormalizedMetadata: ...

    async def artwork(self, kind: str, provider_id: str) -> list[ArtworkCandidate]: ...
