"""Tests for OpenSubtitles provider, hash calculation, and quota handling (written first)."""

from pathlib import Path

import httpx
import pytest
import respx

from metashelf.providers.base import MissingApiKeyError, QuotaExceededError, SubtitleQuery
from metashelf.providers.opensubtitles import OpenSubtitlesProvider, compute_opensubtitles_hash
from metashelf.providers.rate_limit import AsyncRateLimiter

FIXTURES = Path(__file__).parent / "fixtures" / "opensubtitles"


def test_compute_opensubtitles_hash(tmp_path: Path) -> None:
    video = tmp_path / "movie.mkv"
    # 131072 bytes (128 KiB) filled with deterministic bytes
    video.write_bytes(b"\x01\x02\x03\x04" * 32768)
    h = compute_opensubtitles_hash(video)
    assert h is not None
    assert len(h) == 16

    tiny = tmp_path / "tiny.mkv"
    tiny.write_bytes(b"too-small")
    assert compute_opensubtitles_hash(tiny) is None


async def test_opensubtitles_missing_key_raises() -> None:
    async with httpx.AsyncClient() as client:
        os_prov = OpenSubtitlesProvider(api_key="", http_client=client)
        with pytest.raises(MissingApiKeyError):
            await os_prov.search(SubtitleQuery(title="Inception", year=2010, languages=["en"]))


@respx.mock
async def test_opensubtitles_hash_first_search_download_and_quota() -> None:
    search_route = respx.get("https://api.opensubtitles.com/api/v1/subtitles").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "search_en.json").read_text(encoding="utf-8")
        )
    )
    respx.post("https://api.opensubtitles.com/api/v1/login").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "login.json").read_text(encoding="utf-8")
        )
    )
    respx.post("https://api.opensubtitles.com/api/v1/download").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "download_5274788.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://dl.opensubtitles.org/en/download/sub/5274788").mock(
        return_value=httpx.Response(
            200,
            content=b"1\n00:00:01,000 --> 00:00:03,000\nDream within a dream.\n",
        )
    )

    async with httpx.AsyncClient() as client:
        prov = OpenSubtitlesProvider(
            api_key="os-key",
            username="u",
            password="p",
            http_client=client,
            rate_limiter=AsyncRateLimiter(calls_per_second=100.0),
        )
        cands = await prov.search(
            SubtitleQuery(
                title="Inception",
                year=2010,
                movie_hash="a57367d2c203332f",
                tmdb_id="27205",
                languages=["en"],
            )
        )
        assert len(cands) == 1
        assert cands[0].file_id == "5274788"
        assert cands[0].lang == "en"
        assert search_route.calls[0].request.url.params["moviehash"] == "a57367d2c203332f"

        dl = await prov.download(cands[0])
        assert b"Dream within a dream." in dl.content
        assert dl.remaining_quota == 19


@respx.mock
async def test_opensubtitles_quota_exceeded_raises() -> None:
    respx.post("https://api.opensubtitles.com/api/v1/login").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "login.json").read_text(encoding="utf-8")
        )
    )
    respx.post("https://api.opensubtitles.com/api/v1/download").mock(
        return_value=httpx.Response(406, json={"message": "Daily download quota exceeded"})
    )

    from metashelf.providers.base import SubtitleCandidate

    async with httpx.AsyncClient() as client:
        prov = OpenSubtitlesProvider(
            api_key="os-key",
            username="u",
            password="p",
            http_client=client,
            rate_limiter=AsyncRateLimiter(calls_per_second=100.0),
        )
        cand = SubtitleCandidate(
            provider="opensubtitles",
            provider_id="1",
            file_id="5274788",
            lang="en",
            format="srt",
        )
        with pytest.raises(QuotaExceededError):
            await prov.download(cand)
