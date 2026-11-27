"""Tests for artwork downloader, image validation, and SSRF protection."""

from io import BytesIO
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image

from metashelf.writers.artwork import ArtworkDownloadError, download_artwork


def _make_jpeg_bytes(width: int = 100, height: int = 150) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color=(20, 40, 80)).save(buf, format="JPEG")
    return buf.getvalue()


@respx.mock
async def test_download_artwork_validates_and_saves_with_bak(tmp_path: Path) -> None:
    img_bytes = _make_jpeg_bytes(120, 180)
    url = "https://image.tmdb.org/t/p/original/poster.jpg"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            content=img_bytes,
            headers={"content-type": "image/jpeg"},
        )
    )

    target = tmp_path / "Inception (2010)-poster.jpg"
    target.write_bytes(b"old-poster")

    async with httpx.AsyncClient() as client:
        info = await download_artwork(client, url, target)

    assert info.width == 120
    assert info.height == 180
    assert target.read_bytes() == img_bytes
    assert (tmp_path / "Inception (2010)-poster.jpg.bak").read_bytes() == b"old-poster"


@respx.mock
async def test_download_artwork_rejects_bad_content_type(tmp_path: Path) -> None:
    url = "https://image.tmdb.org/t/p/original/bad.jpg"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            content=b"<html>not an image</html>",
            headers={"content-type": "text/html"},
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArtworkDownloadError):
            await download_artwork(client, url, tmp_path / "poster.jpg")


async def test_download_artwork_rejects_ssrf_local_url(tmp_path: Path) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArtworkDownloadError):
            await download_artwork(client, "http://127.0.0.1:8080/secret.jpg", tmp_path / "p.jpg")
