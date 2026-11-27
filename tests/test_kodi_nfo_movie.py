"""Tests for Kodi movie NFO writer, reader round-trip, unknown tag preservation, and .bak."""

from pathlib import Path

from lxml import etree

from metashelf.readers.kodi_nfo_movie import read_movie_nfo
from metashelf.writers.kodi_nfo_movie import write_movie_nfo

GOLDEN = Path(__file__).parent / "fixtures" / "nfo" / "inception_golden.nfo"


def _normalize_xml(xml_bytes: bytes) -> str:
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_bytes, parser)
    return etree.tostring(root, encoding="unicode", pretty_print=True)


def test_nfo_golden_round_trip_and_unknown_preservation(tmp_path: Path) -> None:
    parsed = read_movie_nfo(GOLDEN)
    assert parsed.metadata.title == "Inception"
    assert parsed.metadata.tmdb_id == "27205"
    assert parsed.metadata.imdb_id == "tt1375666"
    assert parsed.metadata.genres == ["Action", "Science Fiction"]
    assert len(parsed.unknown_elements) == 2
    assert {el.tag for el in parsed.unknown_elements} == {"playcount", "dateadded"}

    out_path = tmp_path / "Inception (2010).nfo"
    write_movie_nfo(out_path, parsed.metadata, unknown_elements=parsed.unknown_elements)

    assert _normalize_xml(out_path.read_bytes()) == _normalize_xml(GOLDEN.read_bytes())

    # Re-read written file
    reparsed = read_movie_nfo(out_path)
    assert reparsed.metadata == parsed.metadata
    assert {el.tag for el in reparsed.unknown_elements} == {"playcount", "dateadded"}


def test_nfo_atomic_write_creates_bak_on_overwrite(tmp_path: Path) -> None:
    parsed = read_movie_nfo(GOLDEN)
    out_path = tmp_path / "Movie.nfo"
    out_path.write_text("<movie><title>Old</title></movie>", encoding="utf-8")

    write_movie_nfo(out_path, parsed.metadata)

    bak_path = tmp_path / "Movie.nfo.bak"
    assert bak_path.exists()
    assert "<title>Old</title>" in bak_path.read_text(encoding="utf-8")
    assert "<title>Inception</title>" in out_path.read_text(encoding="utf-8")
    # No leftover temp files
    leftovers = [p for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert leftovers == []
