"""OPF XML sidecar writer for ebooks."""

from copy import deepcopy
from pathlib import Path
from typing import cast

from lxml import etree

from metashelf.domain.models import EbookMetadata
from metashelf.readers.opf_ebook import DC_NS, OPF_NS
from metashelf.writers.atomic import atomic_write_bytes


def render_opf(
    meta: EbookMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> bytes:
    """Serialize EbookMetadata to OPF 3.0 XML bytes preserving unknown metadata elements."""
    nsmap = cast(dict[str, str], {None: OPF_NS, "dc": DC_NS, "opf": OPF_NS})
    package = etree.Element(
        f"{{{OPF_NS}}}package",
        nsmap=nsmap,
        version="3.0",
    )
    package.set("unique-identifier", "pub-id")
    metadata_el = etree.SubElement(package, f"{{{OPF_NS}}}metadata")

    def _dc(tag: str, text: str, **attribs: str) -> etree._Element | None:
        if not text:
            return None
        el = etree.SubElement(metadata_el, f"{{{DC_NS}}}{tag}")
        el.text = text
        for k, v in attribs.items():
            el.set(k, v)
        return el

    _dc("title", meta.title)
    for idx, author in enumerate(meta.authors, start=1):
        _dc("creator", author, id=f"creator{idx:02d}")

    if meta.isbn:
        ident = etree.SubElement(metadata_el, f"{{{DC_NS}}}identifier", id="pub-id")
        ident.set(f"{{{OPF_NS}}}scheme", "ISBN")
        ident.text = meta.isbn
    if meta.openlibrary_id:
        ol_el = etree.SubElement(metadata_el, f"{{{DC_NS}}}identifier")
        ol_el.set(f"{{{OPF_NS}}}scheme", "OPENLIBRARY")
        ol_el.text = meta.openlibrary_id
    if meta.googlebooks_id:
        gb_el = etree.SubElement(metadata_el, f"{{{DC_NS}}}identifier")
        gb_el.set(f"{{{OPF_NS}}}scheme", "GOOGLEBOOKS")
        gb_el.text = meta.googlebooks_id

    _dc("publisher", meta.publisher)
    _dc("date", meta.published_date or (str(meta.year) if meta.year else ""))
    _dc("language", meta.language)
    _dc("description", meta.description)
    for subj in meta.subjects:
        _dc("subject", subj)

    if meta.series:
        coll = etree.SubElement(
            metadata_el,
            f"{{{OPF_NS}}}meta",
            property="belongs-to-collection",
            id="coll01",
        )
        coll.text = meta.series
        ctype = etree.SubElement(
            metadata_el,
            f"{{{OPF_NS}}}meta",
            refines="#coll01",
            property="collection-type",
        )
        ctype.text = "series"
        if meta.series_index:
            pos = etree.SubElement(
                metadata_el,
                f"{{{OPF_NS}}}meta",
                refines="#coll01",
                property="group-position",
            )
            pos.text = meta.series_index

    if unknown_elements:
        for el in unknown_elements:
            metadata_el.append(deepcopy(el))

    return etree.tostring(
        package,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
        standalone=True,
    )


def write_opf(
    target: Path,
    meta: EbookMetadata,
    unknown_elements: list[etree._Element] | None = None,
) -> None:
    """Atomically write <ebook>.opf with .bak backup."""
    atomic_write_bytes(target, render_opf(meta, unknown_elements=unknown_elements))
