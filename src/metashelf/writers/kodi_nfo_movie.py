"""Kodi movie NFO XML writer."""

from copy import deepcopy
from pathlib import Path

from lxml import etree

from metashelf.domain.models import MovieMetadata
from metashelf.writers.atomic import atomic_write_bytes


def _add_text(parent: etree._Element, tag: str, value: str | None) -> None:
    if value:
        el = etree.SubElement(parent, tag)
        el.text = value


def render_movie_nfo(
    meta: MovieMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> bytes:
    """Serialize MovieMetadata (plus preserved unknown XML elements) to Kodi NFO XML bytes."""
    root = etree.Element("movie")

    _add_text(root, "title", meta.title)
    _add_text(root, "originaltitle", meta.original_title)
    _add_text(root, "sorttitle", meta.sort_title)

    if meta.rating is not None:
        ratings_el = etree.SubElement(root, "ratings")
        rating_el = etree.SubElement(
            ratings_el,
            "rating",
            name="tmdb",
            max="10",
            default="true",
        )
        _add_text(rating_el, "value", str(meta.rating))
        if meta.votes is not None:
            _add_text(rating_el, "votes", str(meta.votes))

    if meta.year is not None:
        _add_text(root, "year", str(meta.year))
    _add_text(root, "premiered", meta.premiered)
    _add_text(root, "outline", meta.outline)
    _add_text(root, "plot", meta.plot)
    _add_text(root, "tagline", meta.tagline)
    if meta.runtime is not None:
        _add_text(root, "runtime", str(meta.runtime))
    _add_text(root, "mpaa", meta.mpaa)

    if meta.tmdb_id:
        uid_tmdb = etree.SubElement(root, "uniqueid", type="tmdb", default="true")
        uid_tmdb.text = meta.tmdb_id
    if meta.imdb_id:
        uid_imdb = etree.SubElement(
            root,
            "uniqueid",
            type="imdb",
            default="false" if meta.tmdb_id else "true",
        )
        uid_imdb.text = meta.imdb_id

    for genre in meta.genres:
        _add_text(root, "genre", genre)
    for country in meta.countries:
        _add_text(root, "country", country)
    for studio in meta.studios:
        _add_text(root, "studio", studio)
    for director in meta.directors:
        _add_text(root, "director", director)
    for writer in meta.writers:
        _add_text(root, "credits", writer)
    for tag in meta.tags:
        _add_text(root, "tag", tag)

    if meta.collection:
        set_el = etree.SubElement(root, "set")
        _add_text(set_el, "name", meta.collection)

    _add_text(root, "trailer", meta.trailer)

    for actor in meta.actors:
        actor_el = etree.SubElement(root, "actor")
        _add_text(actor_el, "name", actor.name)
        _add_text(actor_el, "role", actor.role)
        if actor.order is not None:
            _add_text(actor_el, "order", str(actor.order))
        _add_text(actor_el, "thumb", actor.thumb)

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


def write_movie_nfo(
    target: Path,
    meta: MovieMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> None:
    """Atomically write a Kodi movie NFO file with .bak backup."""
    xml_bytes = render_movie_nfo(meta, unknown_elements=unknown_elements)
    atomic_write_bytes(target, xml_bytes)
