"""Kodi tvshow.nfo and episode NFO XML readers."""

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from metashelf.domain.models import ActorCredit, EpisodeMetadata, ShowMetadata

KNOWN_TVSHOW_TAGS = {
    "title",
    "originaltitle",
    "sorttitle",
    "ratings",
    "rating",
    "votes",
    "year",
    "premiered",
    "status",
    "outline",
    "plot",
    "tagline",
    "mpaa",
    "uniqueid",
    "id",
    "genre",
    "studio",
    "country",
    "tag",
    "actor",
    "thumb",
    "fanart",
}

KNOWN_EPISODE_TAGS = {
    "title",
    "showtitle",
    "ratings",
    "rating",
    "votes",
    "season",
    "episode",
    "aired",
    "plot",
    "runtime",
    "uniqueid",
    "id",
    "director",
    "credits",
    "actor",
    "thumb",
}


@dataclass
class ParsedTvShowNfo:
    """Result of reading a tvshow.nfo file."""

    metadata: ShowMetadata
    unknown_elements: list[etree._Element]


@dataclass
class ParsedEpisodeNfo:
    """Result of reading an episode NFO (supports stacked multi-episode blocks)."""

    episodes: list[EpisodeMetadata]
    unknown_elements: list[list[etree._Element]]


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


def _read_ratings(root: etree._Element) -> tuple[float | None, int | None]:
    ratings_el = root.find("ratings")
    if ratings_el is not None:
        chosen = ratings_el.find("rating[@default='true']")
        if chosen is None:
            chosen = ratings_el.find("rating")
        if chosen is not None:
            return (
                _float_or_none(_text(chosen.find("value"))),
                _int_or_none(_text(chosen.find("votes"))),
            )
    return _float_or_none(_text(root.find("rating"))), _int_or_none(_text(root.find("votes")))


def _read_actors(root: etree._Element) -> list[ActorCredit]:
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
    return actors


def read_tvshow_nfo(path: Path) -> ParsedTvShowNfo:
    """Parse a Kodi tvshow.nfo file into ShowMetadata + preserved unknown XML elements."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    tree = etree.parse(str(path), parser)
    root = tree.getroot()
    if root.tag != "tvshow":
        raise ValueError(f"Expected <tvshow> root element in {path}, got <{root.tag}>")

    meta = ShowMetadata()
    meta.title = _text(root.find("title"))
    meta.original_title = _text(root.find("originaltitle"))
    meta.sort_title = _text(root.find("sorttitle"))
    meta.rating, meta.votes = _read_ratings(root)
    meta.year = _int_or_none(_text(root.find("year")))
    meta.premiered = _text(root.find("premiered"))
    meta.status = _text(root.find("status"))
    meta.outline = _text(root.find("outline"))
    meta.plot = _text(root.find("plot"))
    meta.tagline = _text(root.find("tagline"))
    meta.mpaa = _text(root.find("mpaa"))

    for uid in root.findall("uniqueid"):
        uid_type = (uid.get("type") or "").lower()
        val = _text(uid)
        if uid_type == "tmdb" and val:
            meta.tmdb_id = val
        elif uid_type == "tvdb" and val:
            meta.tvdb_id = val
        elif uid_type == "imdb" and val:
            meta.imdb_id = val

    meta.genres = [_text(el) for el in root.findall("genre") if _text(el)]
    meta.studios = [_text(el) for el in root.findall("studio") if _text(el)]
    meta.countries = [_text(el) for el in root.findall("country") if _text(el)]
    meta.tags = [_text(el) for el in root.findall("tag") if _text(el)]
    meta.actors = _read_actors(root)

    unknown = [
        el
        for el in root
        if isinstance(el.tag, str) and el.tag not in KNOWN_TVSHOW_TAGS
    ]
    return ParsedTvShowNfo(metadata=meta, unknown_elements=unknown)


def _parse_single_episodedetails(
    root: etree._Element,
) -> tuple[EpisodeMetadata, list[etree._Element]]:
    ep = EpisodeMetadata()
    ep.title = _text(root.find("title"))
    ep.show_title = _text(root.find("showtitle"))
    ep.rating, ep.votes = _read_ratings(root)
    ep.season = _int_or_none(_text(root.find("season"))) or 0
    ep.episode = _int_or_none(_text(root.find("episode"))) or 1
    ep.episodes = [ep.episode]
    ep.aired = _text(root.find("aired"))
    ep.plot = _text(root.find("plot"))
    ep.runtime = _int_or_none(_text(root.find("runtime")))

    for uid in root.findall("uniqueid"):
        uid_type = (uid.get("type") or "").lower()
        val = _text(uid)
        if uid_type == "tmdb" and val:
            ep.tmdb_id = val
        elif uid_type == "tvdb" and val:
            ep.tvdb_id = val
        elif uid_type == "imdb" and val:
            ep.imdb_id = val

    ep.directors = [_text(el) for el in root.findall("director") if _text(el)]
    ep.writers = [_text(el) for el in root.findall("credits") if _text(el)]
    ep.actors = _read_actors(root)

    unknown = [
        el
        for el in root
        if isinstance(el.tag, str) and el.tag not in KNOWN_EPISODE_TAGS
    ]
    return ep, unknown


def read_episode_nfo(path: Path) -> ParsedEpisodeNfo:
    """Parse a Kodi episode NFO, including multi-episode stacked <episodedetails>."""
    raw = path.read_text(encoding="utf-8")
    # Strip optional XML declaration so we can wrap multiple <episodedetails> blocks safely
    lines = raw.splitlines()
    body = "\n".join(lines[1:]) if lines and lines[0].lstrip().startswith("<?xml") else raw

    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    wrapper = etree.fromstring(f"<_nfo_root>{body}</_nfo_root>".encode(), parser)

    blocks = wrapper.findall("episodedetails")
    if not blocks:
        raise ValueError(f"Expected <episodedetails> in {path}")

    episodes: list[EpisodeMetadata] = []
    unknown_per_block: list[list[etree._Element]] = []
    for block in blocks:
        ep, unk = _parse_single_episodedetails(block)
        episodes.append(ep)
        unknown_per_block.append(unk)
    return ParsedEpisodeNfo(episodes=episodes, unknown_elements=unknown_per_block)
