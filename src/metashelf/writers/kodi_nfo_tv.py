"""Kodi tvshow.nfo and episode NFO XML writers."""

from copy import deepcopy
from pathlib import Path

from lxml import etree

from metashelf.domain.models import ActorCredit, EpisodeMetadata, ShowMetadata
from metashelf.writers.atomic import atomic_write_bytes


def _add_text(parent: etree._Element, tag: str, value: str | None) -> None:
    if value:
        el = etree.SubElement(parent, tag)
        el.text = value


def _write_ratings(
    root: etree._Element,
    rating: float | None,
    votes: int | None,
) -> None:
    if rating is not None:
        ratings_el = etree.SubElement(root, "ratings")
        rating_el = etree.SubElement(ratings_el, "rating", name="tmdb", max="10", default="true")
        _add_text(rating_el, "value", str(rating))
        if votes is not None:
            _add_text(rating_el, "votes", str(votes))


def _write_uniqueids(
    root: etree._Element,
    tmdb_id: str,
    tvdb_id: str,
    imdb_id: str,
) -> None:
    first_set = False
    for uid_type, val in [("tmdb", tmdb_id), ("tvdb", tvdb_id), ("imdb", imdb_id)]:
        if not val:
            continue
        is_default = "true" if not first_set else "false"
        first_set = True
        el = etree.SubElement(root, "uniqueid", type=uid_type, default=is_default)
        el.text = val


def _write_actors(root: etree._Element, actors: list[ActorCredit]) -> None:
    for actor in actors:
        actor_el = etree.SubElement(root, "actor")
        _add_text(actor_el, "name", actor.name)
        _add_text(actor_el, "role", actor.role)
        if actor.order is not None:
            _add_text(actor_el, "order", str(actor.order))
        _add_text(actor_el, "thumb", actor.thumb)


def render_tvshow_nfo(
    meta: ShowMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> bytes:
    """Serialize ShowMetadata to Kodi tvshow.nfo XML bytes."""
    root = etree.Element("tvshow")
    _add_text(root, "title", meta.title)
    _add_text(root, "originaltitle", meta.original_title)
    _add_text(root, "sorttitle", meta.sort_title)
    _write_ratings(root, meta.rating, meta.votes)
    if meta.year is not None:
        _add_text(root, "year", str(meta.year))
    _add_text(root, "premiered", meta.premiered)
    _add_text(root, "status", meta.status)
    _add_text(root, "outline", meta.outline)
    _add_text(root, "plot", meta.plot)
    _add_text(root, "tagline", meta.tagline)
    _add_text(root, "mpaa", meta.mpaa)
    _write_uniqueids(root, meta.tmdb_id, meta.tvdb_id, meta.imdb_id)

    for g in meta.genres:
        _add_text(root, "genre", g)
    for s in meta.studios:
        _add_text(root, "studio", s)
    for c in meta.countries:
        _add_text(root, "country", c)
    for t in meta.tags:
        _add_text(root, "tag", t)
    _write_actors(root, meta.actors)

    if unknown_elements:
        for el in unknown_elements:
            root.append(deepcopy(el))

    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
        standalone=True,
    )


def write_tvshow_nfo(
    target: Path,
    meta: ShowMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> None:
    """Atomically write tvshow.nfo with .bak backup."""
    atomic_write_bytes(target, render_tvshow_nfo(meta, unknown_elements=unknown_elements))


def _build_episodedetails_element(
    ep: EpisodeMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> etree._Element:
    root = etree.Element("episodedetails")
    _add_text(root, "title", ep.title)
    _add_text(root, "showtitle", ep.show_title)
    _write_ratings(root, ep.rating, ep.votes)

    season_el = etree.SubElement(root, "season")
    season_el.text = str(ep.season)
    ep_el = etree.SubElement(root, "episode")
    ep_el.text = str(ep.episode)

    _add_text(root, "aired", ep.aired)
    _add_text(root, "plot", ep.plot)
    if ep.runtime is not None:
        _add_text(root, "runtime", str(ep.runtime))
    _write_uniqueids(root, ep.tmdb_id, ep.tvdb_id, ep.imdb_id)

    for d in ep.directors:
        _add_text(root, "director", d)
    for w in ep.writers:
        _add_text(root, "credits", w)
    _write_actors(root, ep.actors)

    if unknown_elements:
        for el in unknown_elements:
            root.append(deepcopy(el))
    return root


def render_episode_nfo(
    episodes: list[EpisodeMetadata],
    unknown_elements: list[list[etree._Element]] | None = None,
) -> bytes:
    """Serialize one or more EpisodeMetadata blocks to Kodi episode NFO XML bytes."""
    header = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    chunks: list[bytes] = [header]
    for idx, ep in enumerate(episodes):
        unk = unknown_elements[idx] if unknown_elements and idx < len(unknown_elements) else None
        el = _build_episodedetails_element(ep, unknown_elements=unk)
        chunks.append(etree.tostring(el, encoding="UTF-8", pretty_print=True))
    return b"".join(chunks)


def write_episode_nfo(
    target: Path,
    episodes: list[EpisodeMetadata],
    unknown_elements: list[list[etree._Element]] | None = None,
) -> None:
    """Atomically write an episode NFO (supports stacked multi-episode) with .bak backup."""
    atomic_write_bytes(target, render_episode_nfo(episodes, unknown_elements=unknown_elements))
