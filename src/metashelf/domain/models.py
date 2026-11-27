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
