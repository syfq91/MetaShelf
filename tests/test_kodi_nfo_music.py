"""Tests for Kodi artist.nfo and album.nfo readers & writers (written before implementation)."""

from pathlib import Path

from lxml import etree

from metashelf.readers.kodi_nfo_music import read_album_nfo, read_artist_nfo
from metashelf.writers.kodi_nfo_music import write_album_nfo, write_artist_nfo

FIXTURES = Path(__file__).parent / "fixtures" / "nfo"


def _normalize_xml(xml_bytes: bytes) -> str:
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_bytes, parser)
    return etree.tostring(root, encoding="unicode", pretty_print=True)


def test_artist_nfo_golden_round_trip(tmp_path: Path) -> None:
    parsed = read_artist_nfo(FIXTURES / "artist_golden.nfo")
    assert parsed.metadata.name == "Daft Punk"
    assert parsed.metadata.musicbrainz_artist_id == "056e4f3e-d505-4dad-8ec1-d04f521cbb56"
    assert parsed.metadata.formed == "1993"
    assert [el.tag for el in parsed.unknown_elements] == ["customtag"]

    out = tmp_path / "artist.nfo"
    out.write_text("<artist><name>Old</name></artist>", encoding="utf-8")
    write_artist_nfo(out, parsed.metadata, unknown_elements=parsed.unknown_elements)

    assert (tmp_path / "artist.nfo.bak").exists()
    assert _normalize_xml(out.read_bytes()) == _normalize_xml(
        (FIXTURES / "artist_golden.nfo").read_bytes()
    )


def test_album_nfo_golden_round_trip(tmp_path: Path) -> None:
    parsed = read_album_nfo(FIXTURES / "album_golden.nfo")
    assert parsed.metadata.title == "Discovery"
    assert parsed.metadata.artist == "Daft Punk"
    assert parsed.metadata.musicbrainz_album_id == "rel-discovery-14"
    assert len(parsed.metadata.tracks) == 2
    assert [el.tag for el in parsed.unknown_elements] == ["dateadded"]

    out = tmp_path / "album.nfo"
    write_album_nfo(out, parsed.metadata, unknown_elements=parsed.unknown_elements)
    assert _normalize_xml(out.read_bytes()) == _normalize_xml(
        (FIXTURES / "album_golden.nfo").read_bytes()
    )
