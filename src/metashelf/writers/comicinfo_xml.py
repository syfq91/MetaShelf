"""ComicInfo.xml sidecar writer."""

from copy import deepcopy
from pathlib import Path

from lxml import etree

from metashelf.domain.models import ComicMetadata
from metashelf.writers.atomic import atomic_write_bytes


def _add_text(parent: etree._Element, tag: str, value: str | None) -> None:
    if value:
        el = etree.SubElement(parent, tag)
        el.text = value


def render_comicinfo_xml(
    meta: ComicMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> bytes:
    """Serialize ComicMetadata to ComicInfo.xml bytes preserving unknown XML elements."""
    root = etree.Element("ComicInfo")

    _add_text(root, "Title", meta.title)
    _add_text(root, "Series", meta.series)
    _add_text(root, "Number", meta.number)
    if meta.volume is not None:
        _add_text(root, "Volume", str(meta.volume))
    _add_text(root, "Summary", meta.summary)
    if meta.year is not None:
        _add_text(root, "Year", str(meta.year))
    if meta.month is not None:
        _add_text(root, "Month", str(meta.month))
    if meta.day is not None:
        _add_text(root, "Day", str(meta.day))

    _add_text(root, "Writer", ", ".join(meta.writers))
    pencillers = meta.pencillers or meta.artists
    _add_text(root, "Penciller", ", ".join(pencillers))
    _add_text(root, "Inker", ", ".join(meta.inkers))
    _add_text(root, "Colorist", ", ".join(meta.colorists))
    _add_text(root, "Letterer", ", ".join(meta.letterers))
    _add_text(root, "CoverArtist", ", ".join(meta.cover_artists))
    _add_text(root, "Editor", ", ".join(meta.editors))
    _add_text(root, "Publisher", meta.publisher)
    _add_text(root, "Genre", ", ".join(meta.genres))
    if meta.page_count is not None:
        _add_text(root, "PageCount", str(meta.page_count))
    _add_text(root, "Web", meta.web)

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


def write_comicinfo_xml(
    target: Path,
    meta: ComicMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> None:
    """Atomically write <comic>.xml with .bak backup."""
    atomic_write_bytes(target, render_comicinfo_xml(meta, unknown_elements=unknown_elements))
