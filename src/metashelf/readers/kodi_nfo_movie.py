"""Kodi movie NFO XML reader."""

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from metashelf.domain.models import ActorCredit, MovieMetadata

KNOWN_MOVIE_TAGS = {
    "title",
    "originaltitle",
    "sorttitle",
    "year",
    "premiered",
    "outline",
    "plot",
    "tagline",
    "runtime",
    "mpaa",
    "rating",
    "votes",
    "ratings",
    "id",
    "uniqueid",
    "genre",
    "country",
    "studio",
    "director",
    "credits",
    "tag",
    "set",
    "trailer",
    "actor",
    "thumb",
    "fanart",
}


@dataclass
class ParsedMovieNfo:
    """Result of reading a Kodi movie NFO file."""

    metadata: MovieMetadata
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


def read_movie_nfo(path: Path) -> ParsedMovieNfo:
    """Parse a Kodi movie NFO file into MovieMetadata + preserved unknown XML elements."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    tree = etree.parse(str(path), parser)
    root = tree.getroot()
    if root.tag != "movie":
        raise ValueError(f"Expected <movie> root element in {path}, got <{root.tag}>")

    meta = MovieMetadata()
    meta.title = _text(root.find("title"))
    meta.original_title = _text(root.find("originaltitle"))
    meta.sort_title = _text(root.find("sorttitle"))
    meta.year = _int_or_none(_text(root.find("year")))
    meta.premiered = _text(root.find("premiered"))
    meta.outline = _text(root.find("outline"))
    meta.plot = _text(root.find("plot"))
    meta.tagline = _text(root.find("tagline"))
    meta.runtime = _int_or_none(_text(root.find("runtime")))
    meta.mpaa = _text(root.find("mpaa"))
    meta.trailer = _text(root.find("trailer"))

    # Ratings: prefer <ratings><rating ...> then fallback to <rating>/<votes>
    ratings_el = root.find("ratings")
    if ratings_el is not None:
        chosen = ratings_el.find("rating[@default='true']")
        if chosen is None:
            chosen = ratings_el.find("rating")
        if chosen is not None:
            meta.rating = _float_or_none(_text(chosen.find("value")))
            meta.votes = _int_or_none(_text(chosen.find("votes")))
    if meta.rating is None:
        meta.rating = _float_or_none(_text(root.find("rating")))
    if meta.votes is None:
        meta.votes = _int_or_none(_text(root.find("votes")))

    # IDs: <uniqueid type="tmdb|imdb"> and fallback <id>
    for uid in root.findall("uniqueid"):
        uid_type = (uid.get("type") or "").lower()
        val = _text(uid)
        if uid_type == "tmdb" and val:
            meta.tmdb_id = val
        elif uid_type == "imdb" and val:
            meta.imdb_id = val

    legacy_id = _text(root.find("id"))
    if legacy_id and not meta.imdb_id and legacy_id.startswith("tt"):
        meta.imdb_id = legacy_id

    meta.genres = [_text(el) for el in root.findall("genre") if _text(el)]
    meta.countries = [_text(el) for el in root.findall("country") if _text(el)]
    meta.studios = [_text(el) for el in root.findall("studio") if _text(el)]
    meta.directors = [_text(el) for el in root.findall("director") if _text(el)]
    meta.writers = [_text(el) for el in root.findall("credits") if _text(el)]
    meta.tags = [_text(el) for el in root.findall("tag") if _text(el)]

    set_el = root.find("set")
    if set_el is not None:
        name_el = set_el.find("name")
        meta.collection = _text(name_el) if name_el is not None else _text(set_el)

    actors: list[ActorCredit] = []
    for actor_el in root.findall("actor"):
        name = _text(actor_el.find("name"))
        if name:
            actors.append(
                ActorCredit(
                    name=name,
                    role=_text(actor_el.find("role")),
                    order=_int_or_none(_text(actor_el.find("order"))),
                    thumb=_text(actor_el.find("thumb")),
                )
            )
    meta.actors = actors

    unknown = [
        el
        for el in root
        if isinstance(el.tag, str) and el.tag not in KNOWN_MOVIE_TAGS
    ]
    return ParsedMovieNfo(metadata=meta, unknown_elements=unknown)
