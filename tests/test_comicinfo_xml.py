"""Tests for ComicInfo.xml writer/reader round-trip and CBZ first-page cover extraction."""

import zipfile
from io import BytesIO
from pathlib import Path

from lxml import etree
from PIL import Image

from metashelf.readers.comicinfo_xml import read_comicinfo_file
from metashelf.writers.comic_cover import extract_cbz_first_page_cover
from metashelf.writers.comicinfo_xml import write_comicinfo_xml

GOLDEN = Path(__file__).parent / "fixtures" / "comicinfo" / "batman_golden.xml"


def _normalize_xml(xml_bytes: bytes) -> str:
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_bytes, parser)
    return etree.tostring(root, encoding="unicode", pretty_print=True)


def test_comicinfo_golden_round_trip_and_bak(tmp_path: Path) -> None:
    parsed = read_comicinfo_file(GOLDEN)
    assert parsed.metadata.series == "Batman"
    assert parsed.metadata.number == "1"
    assert parsed.metadata.volume == 3
    assert parsed.metadata.writers == ["Tom King"]
    assert [el.tag for el in parsed.unknown_elements] == ["Manga"]

    out = tmp_path / "Batman #001 (2016).xml"
    out.write_text("<ComicInfo><Title>Old</Title></ComicInfo>", encoding="utf-8")
    write_comicinfo_xml(out, parsed.metadata, unknown_elements=parsed.unknown_elements)

    assert (tmp_path / "Batman #001 (2016).xml.bak").exists()
    assert _normalize_xml(out.read_bytes()) == _normalize_xml(GOLDEN.read_bytes())


def test_extract_cbz_first_page_cover_leaves_archive_untouched(tmp_path: Path) -> None:
    buf = BytesIO()
    Image.new("RGB", (180, 260), color=(20, 20, 20)).save(buf, format="PNG")

    cbz_path = tmp_path / "Batman #001.cbz"
    with zipfile.ZipFile(cbz_path, "w") as zf:
        zf.writestr("002.png", buf.getvalue())
        zf.writestr("001.png", buf.getvalue())

    orig_bytes = cbz_path.read_bytes()
    target = tmp_path / "Batman #001.jpg"
    info = extract_cbz_first_page_cover(cbz_path, target)

    assert info is not None
    assert info.width == 180
    assert info.height == 260
    assert target.is_file()
    assert cbz_path.read_bytes() == orig_bytes
