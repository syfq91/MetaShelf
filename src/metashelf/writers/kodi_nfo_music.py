"""Kodi artist.nfo and album.nfo XML writers."""

from copy import deepcopy
from pathlib import Path

from lxml import etree

from metashelf.domain.models import AlbumMetadata, ArtistMetadata
from metashelf.writers.atomic import atomic_write_bytes


def _add_text(parent: etree._Element, tag: str, value: str | None) -> None:
    if value:
        el = etree.SubElement(parent, tag)
        el.text = value


def render_artist_nfo(
    meta: ArtistMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> bytes:
    """Serialize ArtistMetadata to Kodi artist.nfo XML bytes."""
    root = etree.Element("artist")
    _add_text(root, "name", meta.name)
    _add_text(root, "sortname", meta.sort_name)
    _add_text(root, "musicbrainzartistid", meta.musicbrainz_artist_id)
    _add_text(root, "type", meta.artist_type)
    _add_text(root, "gender", meta.gender)
    _add_text(root, "disambiguation", meta.disambiguation)
    _add_text(root, "born", meta.born)
    _add_text(root, "formed", meta.formed)
    _add_text(root, "died", meta.died)
    _add_text(root, "disbanded", meta.disbanded)
    _add_text(root, "yearsactive", meta.years_active)
    _add_text(root, "biography", meta.biography)

    for g in meta.genres:
        _add_text(root, "genre", g)
    for s in meta.styles:
        _add_text(root, "style", s)
    for m in meta.moods:
        _add_text(root, "mood", m)

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


def write_artist_nfo(
    target: Path,
    meta: ArtistMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> None:
    """Atomically write artist.nfo with .bak backup."""
    atomic_write_bytes(target, render_artist_nfo(meta, unknown_elements=unknown_elements))


def render_album_nfo(
    meta: AlbumMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> bytes:
    """Serialize AlbumMetadata to Kodi album.nfo XML bytes."""
    root = etree.Element("album")
    _add_text(root, "title", meta.title)
    _add_text(root, "musicbrainzalbumid", meta.musicbrainz_album_id)
    _add_text(root, "musicbrainzreleasegroupid", meta.musicbrainz_release_group_id)

    if meta.artist or meta.musicbrainz_artist_id:
        credits_el = etree.SubElement(root, "albumArtistCredits")
        _add_text(credits_el, "artist", meta.artist)
        _add_text(credits_el, "musicBrainzArtistID", meta.musicbrainz_artist_id)

    if meta.year is not None:
        _add_text(root, "year", str(meta.year))
    _add_text(root, "releasedate", meta.release_date)
    _add_text(root, "label", meta.label)
    _add_text(root, "type", meta.release_type)
    _add_text(root, "compilation", "true" if meta.compilation else "false")
    _add_text(root, "boxset", "true" if meta.boxset else "false")
    _add_text(root, "review", meta.review)
    if meta.rating is not None:
        r_el = etree.SubElement(root, "rating", max="10")
        r_el.text = str(meta.rating)

    for g in meta.genres:
        _add_text(root, "genre", g)
    for s in meta.styles:
        _add_text(root, "style", s)
    for m in meta.moods:
        _add_text(root, "mood", m)
    for th in meta.themes:
        _add_text(root, "theme", th)

    for t in meta.tracks:
        t_el = etree.SubElement(root, "track")
        _add_text(t_el, "position", str(t.position))
        _add_text(t_el, "title", t.title)
        if t.duration_ms is not None:
            _add_text(t_el, "duration", str(t.duration_ms))

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


def write_album_nfo(
    target: Path,
    meta: AlbumMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> None:
    """Atomically write album.nfo with .bak backup."""
    atomic_write_bytes(target, render_album_nfo(meta, unknown_elements=unknown_elements))
