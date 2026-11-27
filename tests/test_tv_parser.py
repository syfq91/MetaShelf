"""Tests for TV episode filename parsing with guessit (written before implementation)."""

import pytest

from metashelf.scanner.parser import parse_tv_episode_filename


@pytest.mark.parametrize(
    ("rel_path", "expected_show", "expected_season", "expected_episodes"),
    [
        ("Breaking Bad/Season 01/Breaking.Bad.S01E01.720p.mkv", "Breaking Bad", 1, [1]),
        ("Breaking Bad/Season 1/S01E02 - Cat's in the Bag.mkv", "Breaking Bad", 1, [2]),
        ("The Office/Season 02/The.Office.US.S02E01E02.mkv", "The Office", 2, [1, 2]),
        ("Doctor Who (2005)/Specials/Doctor.Who.2005.S00E01.mkv", "Doctor Who", 0, [1]),
        ("Severance/Season 01/1x03.mkv", "Severance", 1, [3]),
        ("Dark/Dark.S03E08.1080p.WEB-DL.mkv", "Dark", 3, [8]),
    ],
)
def test_parse_tv_episode_filename(
    rel_path: str,
    expected_show: str,
    expected_season: int,
    expected_episodes: list[int],
) -> None:
    parsed = parse_tv_episode_filename(rel_path)
    assert parsed.show_title.lower() == expected_show.lower()
    assert parsed.season == expected_season
    assert parsed.episodes == expected_episodes
