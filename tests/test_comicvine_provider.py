"""Tests for Comic Vine provider (written before implementation)."""

from pathlib import Path

import httpx
import pytest
import respx

from metashelf.domain.models import ComicMetadata
from metashelf.providers.base import MissingApiKeyError, SearchQuery
from metashelf.providers.comicvine import ComicVineProvider
from metashelf.providers.rate_limit import AsyncRateLimiter

FIXTURES = Path(__file__).parent / "fixtures" / "comicvine"


async def test_comicvine_missing_key_raises() -> None:
    async with httpx.AsyncClient() as client:
        cv = ComicVineProvider(api_key="", http_client=client)
        with pytest.raises(MissingApiKeyError):
            await cv.search("comic", SearchQuery(title="Batman"))


@respx.mock
async def test_comicvine_volume_search_issues_and_fetch() -> None:
    vol_route = respx.get("https://comicvine.gamespot.com/api/search/").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "search_volume_batman.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://comicvine.gamespot.com/api/issues/").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "volume_91273_issues.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://comicvine.gamespot.com/api/issue/4000-532724/").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "issue_532724.json").read_text(encoding="utf-8")
        )
    )

    async with httpx.AsyncClient() as client:
        cv = ComicVineProvider(
            api_key="cv-key",
            http_client=client,
            rate_limiter=AsyncRateLimiter(calls_per_second=100.0),
        )
        vols = await cv.search("comic", SearchQuery(title="Batman", year=2016))
        assert len(vols) == 1
        assert vols[0].provider_id == "91273"
        assert vols[0].extra["publisher"] == "DC Comics"
        assert "MetaShelf/" in vol_route.calls[0].request.headers["user-agent"]

        issues = await cv.list_volume_issues("91273")
        assert len(issues) == 2
        assert issues[0].number == "1"

        issue = await cv.fetch("comic", "532724", "en")
        assert isinstance(issue, ComicMetadata)
        assert issue.series == "Batman"
        assert issue.title == "I Am Gotham, Part 1"
        assert issue.writers == ["Tom King"]
        assert "David Finch" in issue.pencillers
        assert "Matt Banning" in issue.inkers
        assert "Jordie Bellaire" in issue.colorists

        arts = await cv.artwork("comic", "532724")
        assert len(arts) == 1
        assert arts[0].type == "cover"
