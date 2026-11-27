"""OPF XML reader for sidecar .opf files and embedded EPUB OPF packages."""

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from metashelf.domain.models import EbookMetadata

DC_NS = "http://purl.org/dc/elements/1.1/"
OPF_NS = "http://www.idpf.org/2007/opf"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

_ISBN_RE = re.compile(r"(97[89]\d{10}|\d{9}[\dXx])")

KNOWN_DC_TAGS = {
    f"{{{DC_NS}}}title",
    f"{{{DC_NS}}}creator",
    f"{{{DC_NS}}}identifier",
    f"{{{DC_NS}}}publisher",
    f"{{{DC_NS}}}date",
    f"{{{DC_NS}}}language",
    f"{{{DC_NS}}}description",
    f"{{{DC_NS}}}subject",
}


@dataclass
class ParsedOpf:
    """Result of parsing an OPF XML document."""

    metadata: EbookMetadata
    unknown_elements: list[etree._Element]


def _extract_year(date_str: str) -> int | None:
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


def _clean_isbn(raw: str) -> str:
    compact = raw.replace("-", "").replace(" ", "").strip()
    m = _ISBN_RE.search(compact)
    return m.group(1).upper() if m else ""


def read_opf_bytes(data: bytes) -> ParsedOpf:
    """Parse OPF XML bytes into EbookMetadata + preserved unknown metadata elements."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    root = etree.fromstring(data, parser)
    meta_el = root.find(f"{{{OPF_NS}}}metadata")
    if meta_el is None:
        meta_el = root.find("metadata")
    if meta_el is None:
        raise ValueError("OPF document missing <metadata> element")

    def _dc_texts(local: str) -> list[str]:
        vals: list[str] = []
        for el in meta_el.findall(f"{{{DC_NS}}}{local}"):
            if el.text and el.text.strip():
                vals.append(el.text.strip())
        return vals

    titles = _dc_texts("title")
    creators = _dc_texts("creator")
    publishers = _dc_texts("publisher")
    dates = _dc_texts("date")
    languages = _dc_texts("language")
    descriptions = _dc_texts("description")
    subjects = _dc_texts("subject")

    isbn = ""
    ol_id = ""
    gb_id = ""
    for ident in meta_el.findall(f"{{{DC_NS}}}identifier"):
        val = (ident.text or "").strip()
        if not val:
            continue
        scheme = ""
        for k, v in ident.attrib.items():
            if str(k).endswith("scheme"):
                scheme = str(v).upper()
        if scheme == "OPENLIBRARY":
            ol_id = val
        elif scheme == "GOOGLEBOOKS":
            gb_id = val
        elif not isbn:
            isbn = _clean_isbn(val)

    # Series: support EPUB 3.3 belongs-to-collection & EPUB 2 calibre:series
    series = ""
    series_index = ""
    collection_id = ""
    unknown_elements: list[etree._Element] = []

    all_metas = meta_el.findall(f"{{{OPF_NS}}}meta") + meta_el.findall("meta")
    # Deduplicate in case of namespace matching
    seen_ids: set[int] = set()
    unique_metas: list[etree._Element] = []
    for m in all_metas:
        if id(m) not in seen_ids:
            seen_ids.add(id(m))
            unique_metas.append(m)

    handled_metas: set[int] = set()
    for m in unique_metas:
        prop = m.get("property") or ""
        name = m.get("name") or ""
        if prop == "belongs-to-collection" and m.text and m.text.strip():
            series = m.text.strip()
            collection_id = m.get("id") or ""
            handled_metas.add(id(m))
        elif name == "calibre:series" and m.get("content"):
            series = str(m.get("content")).strip()
            handled_metas.add(id(m))
        elif name == "calibre:series_index" and m.get("content"):
            series_index = str(m.get("content")).strip()
            handled_metas.add(id(m))

    for m in unique_metas:
        prop = m.get("property") or ""
        refines = (m.get("refines") or "").lstrip("#")
        if prop == "group-position" and m.text and m.text.strip():
            if not collection_id or refines == collection_id:
                series_index = m.text.strip()
            handled_metas.add(id(m))
        elif prop == "collection-type" and (not collection_id or refines == collection_id):
            handled_metas.add(id(m))

    for child in meta_el:
        if not isinstance(child.tag, str):
            continue
        if child.tag in KNOWN_DC_TAGS or id(child) in handled_metas:
            continue
        unknown_elements.append(child)

    pub_date = dates[0] if dates else ""
    ebook_meta = EbookMetadata(
        title=titles[0] if titles else "",
        authors=creators,
        isbn=isbn,
        publisher=publishers[0] if publishers else "",
        published_date=pub_date,
        year=_extract_year(pub_date),
        language=languages[0] if languages else "en",
        description=descriptions[0] if descriptions else "",
        subjects=subjects,
        series=series,
        series_index=series_index,
        openlibrary_id=ol_id,
        googlebooks_id=gb_id,
    )
    return ParsedOpf(metadata=ebook_meta, unknown_elements=unknown_elements)


def read_opf_file(path: Path) -> ParsedOpf:
    """Read and parse a sidecar .opf file."""
    return read_opf_bytes(path.read_bytes())


def read_epub_embedded_opf(epub_path: Path) -> ParsedOpf | None:
    """Read the embedded OPF package inside an EPUB ZIP archive without modifying it."""
    with zipfile.ZipFile(epub_path, "r") as zf:
        names = set(zf.namelist())
        if "META-INF/container.xml" not in names:
            return None
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        container = etree.fromstring(zf.read("META-INF/container.xml"), parser)
        rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
        if rootfile is None:
            rootfile = container.find(".//rootfile")
        if rootfile is None:
            return None
        full_path = rootfile.get("full-path")
        if not full_path or full_path not in names:
            return None
        return read_opf_bytes(zf.read(full_path))
