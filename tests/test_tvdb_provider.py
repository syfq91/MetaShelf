"""Tests for TheTVDB v4 and fanart.tv providers (written before implementation)."""

from pathlib import Path

import httpx
import pytest
import respx

from metashelf.domain.models import ShowMetadata
from metashelf.providers.base import MissingApiKeyError, SearchQuery
from metashelf.providers.fanart import FanartTVProvider
from metashelf.providers.tvdb import TheTVDBProvider

TVDB_FIX = Path(__file__).parent / "fixtures" / "tvdb"
FANART_FIX = Path(__file__).parent / "fixtures" / "fanart"


async def test_tvdb_and_fanart_missing_keys() -> None:
    async with httpx.AsyncClient() as client:
        tvdb = TheTVDBProvider(api_key="", http_client=client)
        with pytest.raises(MissingApiKeyError):
            await tvdb.search("show", SearchQuery(title="Breaking Bad"))

        fanart = FanartTVProvider(api_key="", http_client=client)
        with pytest.raises(MissingApiKeyError):
            await fanart.artwork("show", "81189")


@respx.mock
async def test_tvdb_search_and_fetch() -> None:
    respx.post("https://api4.thetvdb.com/v4/login").mock(
        return_value=httpx.Response(200, text=(TVDB_FIX / "login.json").read_text(encoding="utf-8"))
    )
    respx.get("https://api4.thetvdb.com/v4/search").mock(
        return_value=httpx.Response(
            200, text=(TVDB_FIX / "search.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api4.thetvdb.com/v4/series/81189/extended").mock(
        return_value=httpx.Response(
            200, text=(TVDB_FIX / "series_81189.json").read_text(encoding="utf-8")
        )
    )

    async with httpx.AsyncClient() as client:
        tvdb = TheTVDBProvider(api_key="tvdb-key", http_client=client)
        cands = await tvdb.search("show", SearchQuery(title="Breaking Bad"))
        assert len(cands) == 1
        assert cands[0].provider_id == "81189"

        show = await tvdb.fetch("show", "81189", "eng")
        assert isinstance(show, ShowMetadata)
        assert show.title == "Breaking Bad"
        assert show.tvdb_id == "81189"
        assert show.status == "Ended"


@respx.mock
async def test_fanart_tv_artwork() -> None:
    respx.get("https://webservice.fanart.tv/v3/tv/81189").mock(
        return_value=httpx.Response(
            200, text=(FANART_FIX / "tv_81189.json").read_text(encoding="utf-8")
        )
    )
    async with httpx.AsyncClient() as client:
        fanart = FanartTVProvider(api_key="fanart-key", http_client=client)
        arts = await fanart.artwork("show", "81189")
        assert {a.type for a in arts} == {"poster", "fanart", "banner", "logo"}
