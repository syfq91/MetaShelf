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


class TrackInfo(BaseModel):
    """Track entry inside an album."""

    position: int = 1
    disc: int = 1
    title: str = ""
    duration_ms: int | None = None


class ArtistMetadata(BaseModel):
    """Canonical normalized metadata for a music artist."""

    name: str = ""
    sort_name: str = ""
    musicbrainz_artist_id: str = ""
    artist_type: str = ""  # Group, Person, etc.
    gender: str = ""
    disambiguation: str = ""
    born: str = ""
    formed: str = ""
    died: str = ""
    disbanded: str = ""
    years_active: str = ""
    biography: str = ""
    genres: list[str] = Field(default_factory=list)
    styles: list[str] = Field(default_factory=list)
    moods: list[str] = Field(default_factory=list)


class AlbumMetadata(BaseModel):
    """Canonical normalized metadata for a music album."""

    title: str = ""
    artist: str = ""
    musicbrainz_artist_id: str = ""
    musicbrainz_album_id: str = ""
    musicbrainz_release_group_id: str = ""
    year: int | None = None
    release_date: str = ""
    label: str = ""
    release_type: str = ""  # Album, Single, EP
    compilation: bool = False
    boxset: bool = False
    review: str = ""
    rating: float | None = None
    genres: list[str] = Field(default_factory=list)
    styles: list[str] = Field(default_factory=list)
    moods: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    tracks: list[TrackInfo] = Field(default_factory=list)


class TrackMetadata(BaseModel):
    """Canonical normalized metadata for an audio track."""

    title: str = ""
    artist: str = ""
    album: str = ""
    track_number: int = 1
    disc_number: int = 1
    duration_ms: int | None = None
    year: int | None = None
    musicbrainz_recording_id: str = ""


class EbookMetadata(BaseModel):
    """Canonical normalized metadata for an ebook (EPUB/OPF)."""

    title: str = ""
    authors: list[str] = Field(default_factory=list)
    isbn: str = ""
    publisher: str = ""
    published_date: str = ""  # YYYY or YYYY-MM-DD
    year: int | None = None
    language: str = "en"
    description: str = ""
    subjects: list[str] = Field(default_factory=list)
    series: str = ""
    series_index: str = ""
    openlibrary_id: str = ""
    googlebooks_id: str = ""


class ComicMetadata(BaseModel):
    """Canonical normalized metadata for a comic issue (CBZ / ComicInfo.xml)."""

    title: str = ""
    series: str = ""
    number: str = ""  # Issue number string (e.g. "1", "1.5")
    volume: int | None = None
    year: int | None = None
    month: int | None = None
    day: int | None = None
    publisher: str = ""
    summary: str = ""
    writers: list[str] = Field(default_factory=list)
    artists: list[str] = Field(default_factory=list)  # Penciller / Inker / CoverArtist
    pencillers: list[str] = Field(default_factory=list)
    inkers: list[str] = Field(default_factory=list)
    colorists: list[str] = Field(default_factory=list)
    letterers: list[str] = Field(default_factory=list)
    cover_artists: list[str] = Field(default_factory=list)
    editors: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    page_count: int | None = None
    web: str = ""
    comicvine_volume_id: str = ""
    comicvine_issue_id: str = ""


NormalizedMetadata = (
    MovieMetadata
    | ShowMetadata
    | SeasonMetadata
    | EpisodeMetadata
    | ArtistMetadata
    | AlbumMetadata
    | TrackMetadata
    | EbookMetadata
    | ComicMetadata
)
