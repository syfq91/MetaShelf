"""ComicInfo.xml reader for sidecars (<comic>.xml) and embedded CBZ archives."""

import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from metashelf.domain.models import ComicMetadata

KNOWN_COMICINFO_TAGS = {
    "Title",
    "Series",
    "Number",
    "Volume",
    "Summary",
    "Year",
    "Month",
    "Day",
    "Writer",
    "Penciller",
    "Inker",
    "Colorist",
    "Letterer",
    "CoverArtist",
    "Editor",
    "Publisher",
    "Genre",
    "PageCount",
    "Web",
}


@dataclass
class ParsedComicInfo:
    """Result of reading a ComicInfo.xml document."""

    metadata: ComicMetadata
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


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def read_comicinfo_bytes(data: bytes) -> ParsedComicInfo:
    """Parse ComicInfo.xml bytes into ComicMetadata + preserved unknown XML elements."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    root = etree.fromstring(data, parser)
    if root.tag != "ComicInfo":
        raise ValueError(f"Expected <ComicInfo> root element, got <{root.tag}>")

    pencillers = _split_csv(_text(root.find("Penciller")))
    inkers = _split_csv(_text(root.find("Inker")))
    cover_artists = _split_csv(_text(root.find("CoverArtist")))
    artists: list[str] = []
    for name in pencillers + inkers + cover_artists:
        if name not in artists:
            artists.append(name)

    vol = _int_or_none(_text(root.find("Volume")))
    if vol == -1:
        vol = None

    meta = ComicMetadata(
        title=_text(root.find("Title")),
        series=_text(root.find("Series")),
        number=_text(root.find("Number")),
        volume=vol,
        year=_int_or_none(_text(root.find("Year"))),
        month=_int_or_none(_text(root.find("Month"))),
        day=_int_or_none(_text(root.find("Day"))),
        publisher=_text(root.find("Publisher")),
        summary=_text(root.find("Summary")),
        writers=_split_csv(_text(root.find("Writer"))),
        artists=artists,
        pencillers=pencillers,
        inkers=inkers,
        colorists=_split_csv(_text(root.find("Colorist"))),
        letterers=_split_csv(_text(root.find("Letterer"))),
        cover_artists=cover_artists,
        editors=_split_csv(_text(root.find("Editor"))),
        genres=_split_csv(_text(root.find("Genre"))),
        page_count=_int_or_none(_text(root.find("PageCount"))),
        web=_text(root.find("Web")),
    )
    unknown = [
        el
        for el in root
        if isinstance(el.tag, str) and el.tag not in KNOWN_COMICINFO_TAGS
    ]
    return ParsedComicInfo(metadata=meta, unknown_elements=unknown)


def read_comicinfo_file(path: Path) -> ParsedComicInfo:
    """Read and parse a sidecar <comic>.xml file."""
    return read_comicinfo_bytes(path.read_bytes())


def read_cbz_embedded_comicinfo(cbz_path: Path) -> ParsedComicInfo | None:
    """Read an embedded ComicInfo.xml inside a CBZ ZIP archive without modifying it."""
    with zipfile.ZipFile(cbz_path, "r") as zf:
        for name in zf.namelist():
            if Path(name).name.lower() == "comicinfo.xml":
                return read_comicinfo_bytes(zf.read(name))
    return None
