"""Tests for comic CBZ filename parsing (written before implementation)."""

import pytest

from metashelf.scanner.parser import parse_comic_filename


@pytest.mark.parametrize(
    ("rel_path", "expected_series", "expected_number", "expected_volume", "expected_year"),
    [
        ("Batman/Batman #001 (2016).cbz", "Batman", "1", None, 2016),
        ("Saga/Saga v02 012 (2013).cbz", "Saga", "12", 2, 2013),
        (
            "Spider-Man/Amazing Spider-Man Vol. 3 #005.5 (2014).cbz",
            "Amazing Spider-Man",
            "5.5",
            3,
            2014,
        ),
        ("Invincible/Invincible 025 (2005).cbz", "Invincible", "25", None, 2005),
        ("Sandman/Sandman #01 (1989).cbz", "Sandman", "1", None, 1989),
    ],
)
def test_parse_comic_filename(
    rel_path: str,
    expected_series: str,
    expected_number: str,
    expected_volume: int | None,
    expected_year: int | None,
) -> None:
    parsed = parse_comic_filename(rel_path)
    assert parsed.series.lower() == expected_series.lower()
    assert parsed.number == expected_number
    assert parsed.volume == expected_volume
    assert parsed.year == expected_year
