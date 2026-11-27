"""Tests for movie filename parsing with guessit (written before implementation)."""

import pytest

from metashelf.scanner.parser import parse_movie_filename


@pytest.mark.parametrize(
    ("rel_path", "expected_title", "expected_year"),
    [
        ("Inception (2010)/Inception (2010).mkv", "Inception", 2010),
        ("The.Matrix.1999.1080p.BluRay.x264-GROUP.mkv", "The Matrix", 1999),
        ("Blade Runner 2049 (2017) [2160p].mp4", "Blade Runner 2049", 2017),
        ("Spirited.Away.2001.JAPANESE.1080p.mkv", "Spirited Away", 2001),
        ("2001 A Space Odyssey (1968)/2001.A.Space.Odyssey.1968.mkv", "2001 A Space Odyssey", 1968),
        ("Interstellar.2014.1080p.WEB-DL.mkv", "Interstellar", 2014),
        ("Parasite (2019).avi", "Parasite", 2019),
    ],
)
def test_parse_movie_filename(rel_path: str, expected_title: str, expected_year: int) -> None:
    parsed = parse_movie_filename(rel_path)
    assert parsed.title.lower() == expected_title.lower()
    assert parsed.year == expected_year
