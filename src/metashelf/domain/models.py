"""Canonical Pydantic domain models."""

from enum import StrEnum

from pydantic import BaseModel, Field


class LibraryType(StrEnum):
    MOVIE = "movie"
    TV = "tv"
    MUSIC = "music"
    EBOOK = "ebook"
    COMIC = "comic"


class ItemKind(StrEnum):
    MOVIE = "movie"
    SHOW = "show"
    SEASON = "season"
    EPISODE = "episode"
    ARTIST = "artist"
    ALBUM = "album"
    TRACK = "track"
    EBOOK = "ebook"
    COMIC = "comic"


class ItemState(StrEnum):
    UNMATCHED = "unmatched"
    MATCHED = "matched"
    COMPLETE = "complete"
    DIRTY = "dirty"
    ERROR = "error"


class ArtworkType(StrEnum):
    POSTER = "poster"
    FANART = "fanart"
    BANNER = "banner"
    THUMB = "thumb"
    COVER = "cover"
    LOGO = "logo"


class ActorCredit(BaseModel):
    """Cast member credit."""

    name: str
    role: str = ""
    order: int | None = None
    thumb: str = ""


class MovieMetadata(BaseModel):
    """Canonical normalized metadata for a movie."""

    title: str = ""
    original_title: str = ""
    sort_title: str = ""
    year: int | None = None
    premiered: str = ""  # YYYY-MM-DD
    tagline: str = ""
    plot: str = ""
    outline: str = ""
    runtime: int | None = None  # minutes
    mpaa: str = ""
    rating: float | None = None
    votes: int | None = None
    imdb_id: str = ""
    tmdb_id: str = ""
    genres: list[str] = Field(default_factory=list)
    studios: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    directors: list[str] = Field(default_factory=list)
    writers: list[str] = Field(default_factory=list)
    actors: list[ActorCredit] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    collection: str = ""
    trailer: str = ""


class ShowMetadata(BaseModel):
    """Canonical normalized metadata for a TV show."""

    title: str = ""
    original_title: str = ""
    sort_title: str = ""
    year: int | None = None
    premiered: str = ""  # YYYY-MM-DD
    status: str = ""  # Continuing, Ended
    tagline: str = ""
    plot: str = ""
    outline: str = ""
    mpaa: str = ""
    rating: float | None = None
    votes: int | None = None
    tmdb_id: str = ""
    tvdb_id: str = ""
    imdb_id: str = ""
    genres: list[str] = Field(default_factory=list)
    studios: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    actors: list[ActorCredit] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class SeasonMetadata(BaseModel):
    """Canonical normalized metadata for a TV season."""

    season_number: int
    title: str = ""
    plot: str = ""
    premiered: str = ""
    tmdb_id: str = ""


class EpisodeMetadata(BaseModel):
    """Canonical normalized metadata for a TV episode (supports multi-episode files)."""

    title: str = ""
    show_title: str = ""
    season: int = 1
    episode: int = 1
    episodes: list[int] = Field(default_factory=list)  # e.g. [1, 2] for S01E01E02
    aired: str = ""  # YYYY-MM-DD
    plot: str = ""
    runtime: int | None = None
    rating: float | None = None
    votes: int | None = None
    tmdb_id: str = ""
    tvdb_id: str = ""
    imdb_id: str = ""
    directors: list[str] = Field(default_factory=list)
    writers: list[str] = Field(default_factory=list)
    actors: list[ActorCredit] = Field(default_factory=list)
    thumb_url: str = ""


NormalizedMetadata = MovieMetadata | ShowMetadata | SeasonMetadata | EpisodeMetadata
