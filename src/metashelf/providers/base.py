"""Provider protocol and shared request/response models."""

from typing import Protocol

from pydantic import BaseModel, Field

from metashelf.domain.models import NormalizedMetadata


class ProviderError(RuntimeError):
    """Base error for metadata providers."""


class MissingApiKeyError(ProviderError):
    """Raised when a provider requires an API key that is not configured."""


class QuotaExceededError(ProviderError):
    """Raised when a provider's daily download or API quota is exhausted."""


class SearchQuery(BaseModel):
    """Normalized search query sent to providers."""

    title: str
    year: int | None = None
    lang: str = "en-US"
    isbn: str | None = None
    author: str | None = None


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


class SubtitleQuery(BaseModel):
    """Normalized search query for subtitles."""

    title: str = ""
    year: int | None = None
    tmdb_id: str = ""
    imdb_id: str = ""
    season: int | None = None
    episode: int | None = None
    movie_hash: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["en"])


class SubtitleCandidate(BaseModel):
    """A subtitle search candidate."""

    provider: str
    provider_id: str
    file_id: str
    lang: str
    format: str = "srt"
    forced: bool = False
    hearing_impaired: bool = False
    synced: bool = False  # True when matched by file hash
    score: float = 0.0
    release_name: str = ""


class SubtitleDownload(BaseModel):
    """Downloaded subtitle file bytes and remaining quota."""

    content: bytes
    file_name: str = ""
    remaining_quota: int | None = None


class SubtitleProvider(Protocol):
    """Async subtitle provider protocol."""

    id: str
    needs_api_key: bool

    async def search(self, query: SubtitleQuery) -> list[SubtitleCandidate]: ...

    async def download(self, candidate: SubtitleCandidate) -> SubtitleDownload: ...


class LyricsQuery(BaseModel):
    """Normalized search query for track lyrics."""

    title: str
    artist: str
    album: str = ""
    duration_seconds: int | None = None


class LyricsCandidate(BaseModel):
    """A track lyrics candidate."""

    provider: str
    provider_id: str
    lang: str = "en"
    format: str = "lrc"  # lrc or txt
    synced: bool = False
    score: float = 0.0
    text: str = ""


class LyricsProvider(Protocol):
    """Async lyrics provider protocol."""

    id: str
    needs_api_key: bool

    async def search(self, query: LyricsQuery) -> list[LyricsCandidate]: ...
