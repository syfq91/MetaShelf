"""Tests for OPF sidecar writer and reader round-trip (written before implementation)."""

from pathlib import Path

from lxml import etree

from metashelf.readers.opf_ebook import read_opf_file
from metashelf.writers.opf_ebook import write_opf

GOLDEN = Path(__file__).parent / "fixtures" / "opf" / "dune_golden.opf"


def _normalize_xml(xml_bytes: bytes) -> str:
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_bytes, parser)
    return etree.tostring(root, encoding="unicode", pretty_print=True)


def test_opf_golden_round_trip_multiple_authors_series_and_bak(tmp_path: Path) -> None:
    parsed = read_opf_file(GOLDEN)
    assert parsed.metadata.title == "Dune"
    assert parsed.metadata.authors == ["Frank Herbert", "Brian Herbert"]
    assert parsed.metadata.isbn == "9780441172719"
    assert parsed.metadata.series == "Dune Chronicles"
    assert parsed.metadata.series_index == "1"
    assert parsed.metadata.openlibrary_id == "works/OL893415W"
    assert len(parsed.unknown_elements) == 1

    out = tmp_path / "Dune.opf"
    out.write_text("<package><metadata/></package>", encoding="utf-8")
    write_opf(out, parsed.metadata, unknown_elements=parsed.unknown_elements)

    assert (tmp_path / "Dune.opf.bak").exists()
    assert _normalize_xml(out.read_bytes()) == _normalize_xml(GOLDEN.read_bytes())
