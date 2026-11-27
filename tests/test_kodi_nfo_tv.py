"""Tests for Kodi tvshow.nfo and episode NFO readers & writers (written before implementation)."""

from pathlib import Path

from lxml import etree

from metashelf.readers.kodi_nfo_tv import read_episode_nfo, read_tvshow_nfo
from metashelf.writers.kodi_nfo_tv import write_episode_nfo, write_tvshow_nfo

FIXTURES = Path(__file__).parent / "fixtures" / "nfo"


def _normalize_xml(xml_bytes: bytes) -> str:
    parser = etree.XMLParser(remove_blank_text=True, recover=False)
    root = etree.fromstring(xml_bytes, parser)
    return etree.tostring(root, encoding="unicode", pretty_print=True)


def test_tvshow_nfo_golden_round_trip_and_unknown_preservation(tmp_path: Path) -> None:
    parsed = read_tvshow_nfo(FIXTURES / "tvshow_golden.nfo")
    assert parsed.metadata.title == "Breaking Bad"
    assert parsed.metadata.tmdb_id == "1396"
    assert parsed.metadata.tvdb_id == "81189"
    assert parsed.metadata.imdb_id == "tt0903747"
    assert parsed.metadata.status == "Ended"
    assert [el.tag for el in parsed.unknown_elements] == ["episodeguide"]

    out = tmp_path / "tvshow.nfo"
    write_tvshow_nfo(out, parsed.metadata, unknown_elements=parsed.unknown_elements)
    assert _normalize_xml(out.read_bytes()) == _normalize_xml(
        (FIXTURES / "tvshow_golden.nfo").read_bytes()
    )


def test_episode_nfo_golden_round_trip_and_bak(tmp_path: Path) -> None:
    parsed = read_episode_nfo(FIXTURES / "episode_golden.nfo")
    assert len(parsed.episodes) == 1
    ep = parsed.episodes[0]
    assert ep.title == "Pilot"
    assert ep.season == 1
    assert ep.episode == 1
    assert [el.tag for el in parsed.unknown_elements[0]] == ["watched"]

    out = tmp_path / "Breaking.Bad.S01E01.nfo"
    out.write_text("<episodedetails><title>Old</title></episodedetails>", encoding="utf-8")
    write_episode_nfo(out, parsed.episodes, unknown_elements=parsed.unknown_elements)

    assert (tmp_path / "Breaking.Bad.S01E01.nfo.bak").exists()
    assert _normalize_xml(out.read_bytes()) == _normalize_xml(
        (FIXTURES / "episode_golden.nfo").read_bytes()
    )


def test_multi_episode_stacked_nfo_round_trip(tmp_path: Path) -> None:
    parsed = read_episode_nfo(FIXTURES / "multi_episode_golden.nfo")
    assert len(parsed.episodes) == 2
    assert parsed.episodes[0].episode == 2
    assert parsed.episodes[1].episode == 3

    out = tmp_path / "S01E02E03.nfo"
    write_episode_nfo(out, parsed.episodes)

    reparsed = read_episode_nfo(out)
    assert len(reparsed.episodes) == 2
    assert reparsed.episodes[0].title == "Part One"
    assert reparsed.episodes[1].title == "Part Two"
