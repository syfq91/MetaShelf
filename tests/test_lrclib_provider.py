"""Tests for LRCLIB lyrics provider (written before implementation)."""

from pathlib import Path

import httpx
import respx

from metashelf.providers.base import LyricsQuery
from metashelf.providers.lrclib import LRCLIBProvider
from metashelf.providers.rate_limit import AsyncRateLimiter

FIXTURES = Path(__file__).parent / "fixtures" / "lrclib"


@respx.mock
async def test_lrclib_synced_first_and_search_plain_fallback() -> None:
    respx.get("https://lrclib.net/api/get").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "get_one_more_time.json").read_text(encoding="utf-8")
        )
    )

    async with httpx.AsyncClient() as client:
        prov = LRCLIBProvider(
            http_client=client,
            rate_limiter=AsyncRateLimiter(calls_per_second=100.0),
        )
        cands = await prov.search(
            LyricsQuery(
                title="One More Time",
                artist="Daft Punk",
                album="Discovery",
                duration_seconds=320,
            )
        )
        assert len(cands) == 2
        # Synced LRC is ranked first
        assert cands[0].synced is True
        assert cands[0].format == "lrc"
        assert "[00:45.10]" in cands[0].text
        assert cands[1].synced is False
        assert cands[1].format == "txt"


@respx.mock
async def test_lrclib_falls_back_to_search_when_get_404() -> None:
    respx.get("https://lrclib.net/api/get").mock(return_value=httpx.Response(404))
    respx.get("https://lrclib.net/api/search").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "search_aerodynamic.json").read_text(encoding="utf-8")
        )
    )

    async with httpx.AsyncClient() as client:
        prov = LRCLIBProvider(
            http_client=client,
            rate_limiter=AsyncRateLimiter(calls_per_second=100.0),
        )
        cands = await prov.search(
            LyricsQuery(title="Aerodynamic", artist="Daft Punk", duration_seconds=207)
        )
        assert len(cands) == 1
        assert cands[0].synced is False
        assert cands[0].format == "txt"
