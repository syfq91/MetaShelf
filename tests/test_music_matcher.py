"""Tests for album release disambiguation using track count and track titles (written first)."""

from metashelf.domain.models import TrackInfo
from metashelf.matching.music import pick_album_release, score_album_release
from metashelf.providers.base import Candidate


def test_album_disambiguation_prefers_matching_track_count_and_titles() -> None:
    local_tracks = [
        TrackInfo(position=1, title="One More Time"),
        TrackInfo(position=2, title="Aerodynamic"),
    ]
    # Release A has 2 tracks matching titles; Release B has 15 tracks (Japanese bonus edition)
    cand_a = Candidate(
        provider="musicbrainz",
        provider_id="rel-2",
        title="Discovery",
        year=2001,
        extra={"track_count": "2", "artist": "Daft Punk"},
    )
    cand_b = Candidate(
        provider="musicbrainz",
        provider_id="rel-15",
        title="Discovery",
        year=2001,
        extra={"track_count": "15", "artist": "Daft Punk"},
    )
    score_a = score_album_release("Discovery", "Daft Punk", 2001, local_tracks, cand_a)
    score_b = score_album_release("Discovery", "Daft Punk", 2001, local_tracks, cand_b)
    assert score_a > score_b

    picked = pick_album_release("Discovery", "Daft Punk", 2001, local_tracks, [cand_b, cand_a])
    assert picked is not None
    assert picked.provider_id == "rel-2"
