"""Tests for MusicBrainz provider (strict User-Agent, rate limiter, search, fetch)."""

from pathlib import Path

import httpx
import respx

from metashelf.domain.models import AlbumMetadata, ArtistMetadata
from metashelf.providers.base import SearchQuery
from metashelf.providers.musicbrainz import MusicBrainzProvider
from metashelf.providers.rate_limit import AsyncRateLimiter

FIXTURES = Path(__file__).parent / "fixtures" / "musicbrainz"


@respx.mock
async def test_musicbrainz_artist_and_album_search_fetch() -> None:
    artist_search_route = respx.get("https://musicbrainz.org/ws/2/artist").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "search_artist_daft_punk.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://musicbrainz.org/ws/2/artist/056e4f3e-d505-4dad-8ec1-d04f521cbb56"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "artist_daft_punk.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://musicbrainz.org/ws/2/release").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "search_release_discovery.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://musicbrainz.org/ws/2/release/rel-discovery-14").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "release_discovery_14.json").read_text(encoding="utf-8")
        )
    )

    async with httpx.AsyncClient() as client:
        # Fast limiter in test while verifying default limiter is 1 req/s
        default_provider = MusicBrainzProvider(http_client=client)
        assert default_provider.rate_limiter_interval >= 1.0

        provider = MusicBrainzProvider(
            http_client=client,
            rate_limiter=AsyncRateLimiter(calls_per_second=100.0),
        )
        artists = await provider.search("artist", SearchQuery(title="Daft Punk"))
        assert len(artists) == 1
        assert artists[0].provider_id == "056e4f3e-d505-4dad-8ec1-d04f521cbb56"
        assert "MetaShelf/" in artist_search_route.calls[0].request.headers["user-agent"]

        artist = await provider.fetch(
            "artist", "056e4f3e-d505-4dad-8ec1-d04f521cbb56", "en"
        )
        assert isinstance(artist, ArtistMetadata)
        assert artist.name == "Daft Punk"
        assert artist.formed == "1993"
        assert "electronic" in artist.genres

        releases = await provider.search("album", SearchQuery(title="Discovery", year=2001))
        assert len(releases) == 2
        assert releases[0].extra["track_count"] == "14"

        album = await provider.fetch("album", "rel-discovery-14", "en")
        assert isinstance(album, AlbumMetadata)
        assert album.title == "Discovery"
        assert album.label == "Virgin"
        assert len(album.tracks) == 2
        assert album.tracks[0].title == "One More Time"
