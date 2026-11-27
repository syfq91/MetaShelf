"""Tests for TMDB TV provider (written before implementation)."""

from pathlib import Path

import httpx
import respx

from metashelf.domain.models import ShowMetadata
from metashelf.providers.base import SearchQuery
from metashelf.providers.tmdb import TMDBProvider

FIXTURES = Path(__file__).parent / "fixtures" / "tmdb"


@respx.mock
async def test_tmdb_tv_search_fetch_season_and_artwork() -> None:
    respx.get("https://api.themoviedb.org/3/search/tv").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "search_tv_breaking_bad.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/tv/1396").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "tv_1396.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/tv/1396/season/1").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "tv_1396_s1.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/tv/1396/images").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "tv_1396_images.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/tv/1396/season/1/images").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "tv_1396_s1_images.json").read_text(encoding="utf-8")
        )
    )

    async with httpx.AsyncClient() as client:
        provider = TMDBProvider(api_key="dummy-key", http_client=client)
        cands = await provider.search("show", SearchQuery(title="Breaking Bad", year=2008))
        assert len(cands) == 1
        assert cands[0].provider_id == "1396"
        assert cands[0].year == 2008

        show = await provider.fetch("show", "1396", "en-US")
        assert isinstance(show, ShowMetadata)
        assert show.title == "Breaking Bad"
        assert show.tvdb_id == "81189"
        assert show.imdb_id == "tt0903747"
        assert show.mpaa == "TV-MA"
        assert show.status == "Ended"

        episodes = await provider.fetch_season_episodes("1396", 1, "Breaking Bad", "en-US")
        assert len(episodes) == 2
        assert episodes[0].title == "Pilot"
        assert episodes[0].runtime == 58
        assert "Vince Gilligan" in episodes[0].directors
        assert "image.tmdb.org" in episodes[0].thumb_url

        show_art = await provider.artwork("show", "1396")
        assert {a.type for a in show_art} == {"poster", "fanart"}

        s1_art = await provider.season_artwork("1396", 1)
        assert len(s1_art) == 1
        assert s1_art[0].type == "poster"
