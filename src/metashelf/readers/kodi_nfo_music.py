"""Kodi artist.nfo and album.nfo XML readers."""

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from metashelf.domain.models import AlbumMetadata, ArtistMetadata, TrackInfo

KNOWN_ARTIST_TAGS = {
    "name",
    "sortname",
    "musicbrainzartistid",
    "type",
    "gender",
    "disambiguation",
    "born",
    "formed",
    "died",
    "disbanded",
    "yearsactive",
    "biography",
    "genre",
    "style",
    "mood",
}

KNOWN_ALBUM_TAGS = {
    "title",
    "musicbrainzalbumid",
    "musicbrainzreleasegroupid",
    "albumArtistCredits",
    "year",
    "releasedate",
    "label",
    "type",
    "compilation",
    "boxset",
    "review",
    "rating",
    "genre",
    "style",
    "mood",
    "theme",
    "track",
}


@dataclass
class ParsedArtistNfo:
    """Result of reading an artist.nfo file."""

    metadata: ArtistMetadata
    unknown_elements: list[etree._Element]


@dataclass
class ParsedAlbumNfo:
    """Result of reading an album.nfo file."""

    metadata: AlbumMetadata
    unknown_elements: list[etree._Element]


def _text(el: etree._Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _int_or_none(raw: str) -> int | None:
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _float_or_none(raw: str) -> float | None:
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def read_artist_nfo(path: Path) -> ParsedArtistNfo:
    """Parse Kodi artist.nfo into ArtistMetadata + preserved unknown XML elements."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    tree = etree.parse(str(path), parser)
    root = tree.getroot()
    if root.tag != "artist":
        raise ValueError(f"Expected <artist> root element in {path}, got <{root.tag}>")

    meta = ArtistMetadata(
        name=_text(root.find("name")),
        sort_name=_text(root.find("sortname")),
        musicbrainz_artist_id=_text(root.find("musicbrainzartistid")),
        artist_type=_text(root.find("type")),
        gender=_text(root.find("gender")),
        disambiguation=_text(root.find("disambiguation")),
        born=_text(root.find("born")),
        formed=_text(root.find("formed")),
        died=_text(root.find("died")),
        disbanded=_text(root.find("disbanded")),
        years_active=_text(root.find("yearsactive")),
        biography=_text(root.find("biography")),
        genres=[_text(el) for el in root.findall("genre") if _text(el)],
        styles=[_text(el) for el in root.findall("style") if _text(el)],
        moods=[_text(el) for el in root.findall("mood") if _text(el)],
    )
    unknown = [
        el
        for el in root
        if isinstance(el.tag, str) and el.tag not in KNOWN_ARTIST_TAGS
    ]
    return ParsedArtistNfo(metadata=meta, unknown_elements=unknown)


def read_album_nfo(path: Path) -> ParsedAlbumNfo:
    """Parse Kodi album.nfo into AlbumMetadata + preserved unknown XML elements."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    tree = etree.parse(str(path), parser)
    root = tree.getroot()
    if root.tag != "album":
        raise ValueError(f"Expected <album> root element in {path}, got <{root.tag}>")

    credits_el = root.find("albumArtistCredits")
    artist_name = _text(credits_el.find("artist")) if credits_el is not None else ""
    artist_mbid = _text(credits_el.find("musicBrainzArtistID")) if credits_el is not None else ""

    tracks: list[TrackInfo] = []
    for t_el in root.findall("track"):
        title = _text(t_el.find("title"))
        pos = _int_or_none(_text(t_el.find("position"))) or len(tracks) + 1
        dur = _int_or_none(_text(t_el.find("duration")))
        tracks.append(TrackInfo(position=pos, title=title, duration_ms=dur))

    meta = AlbumMetadata(
        title=_text(root.find("title")),
        artist=artist_name,
        musicbrainz_artist_id=artist_mbid,
        musicbrainz_album_id=_text(root.find("musicbrainzalbumid")),
        musicbrainz_release_group_id=_text(root.find("musicbrainzreleasegroupid")),
        year=_int_or_none(_text(root.find("year"))),
        release_date=_text(root.find("releasedate")),
        label=_text(root.find("label")),
        release_type=_text(root.find("type")),
        compilation=_text(root.find("compilation")).lower() == "true",
        boxset=_text(root.find("boxset")).lower() == "true",
        review=_text(root.find("review")),
        rating=_float_or_none(_text(root.find("rating"))),
        genres=[_text(el) for el in root.findall("genre") if _text(el)],
        styles=[_text(el) for el in root.findall("style") if _text(el)],
        moods=[_text(el) for el in root.findall("mood") if _text(el)],
        themes=[_text(el) for el in root.findall("theme") if _text(el)],
        tracks=tracks,
    )
    unknown = [
        el
        for el in root
        if isinstance(el.tag, str) and el.tag not in KNOWN_ALBUM_TAGS
    ]
    return ParsedAlbumNfo(metadata=meta, unknown_elements=unknown)
