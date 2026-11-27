"""Tests for movie auto-match scoring and confidence threshold (written before implementation)."""

from metashelf.matching.movie import pick_auto_match, score_movie_candidate
from metashelf.providers.base import Candidate


def test_high_confidence_exact_match_accepted() -> None:
    c1 = Candidate(provider="tmdb", provider_id="27205", title="Inception", year=2010)
    c2 = Candidate(
        provider="tmdb",
        provider_id="999",
        title="Inception: The Cobol Job",
        year=2010,
    )
    assert score_movie_candidate("Inception", 2010, c1) == 1.0
    picked = pick_auto_match("Inception", 2010, [c2, c1])
    assert picked is not None
    assert picked.provider_id == "27205"


def test_ambiguous_margin_leaves_unmatched() -> None:
    c1 = Candidate(provider="tmdb", provider_id="1", title="The Thing", year=1982)
    c2 = Candidate(provider="tmdb", provider_id="2", title="The Thing", year=1982)
    picked = pick_auto_match("The Thing", 1982, [c1, c2])
    assert picked is None


def test_low_confidence_wrong_year_rejected() -> None:
    c1 = Candidate(provider="tmdb", provider_id="1", title="Dune", year=1984)
    picked = pick_auto_match("Dune", 2021, [c1])
    assert picked is None
