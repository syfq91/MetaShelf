"""Tests for Cover Art Archive provider and redirect-safe artwork downloads."""

from io import BytesIO
from pathlib import Path

import httpx
import respx
from PIL import Image

from metashelf.providers.coverart import CoverArtArchiveProvider
from metashelf.writers.artwork import download_artwork

FIXTURES = Path(__file__).parent / "fixtures" / "coverart"


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (200, 200), color=(90, 20, 40)).save(buf, format="JPEG")
    return buf.getvalue()


@respx.mock
async def test_coverart_archive_and_redirect_download(tmp_path: Path) -> None:
    respx.get("https://coverartarchive.org/release/rel-discovery-14").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "release_discovery.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://coverartarchive.org/release/rel-discovery-14/front").mock(
        return_value=httpx.Response(
            307,
            headers={"Location": "https://archive.org/download/mbid-rel-discovery-14/front.jpg"},
        )
    )
    respx.get("https://archive.org/download/mbid-rel-discovery-14/front.jpg").mock(
        return_value=httpx.Response(
            200, content=_jpeg_bytes(), headers={"content-type": "image/jpeg"}
        )
    )

    async with httpx.AsyncClient() as client:
        caa = CoverArtArchiveProvider(http_client=client)
        arts = await caa.artwork("album", "rel-discovery-14")
        assert len(arts) == 1
        assert arts[0].type == "cover"

        dl = await download_artwork(
            client,
            "https://coverartarchive.org/release/rel-discovery-14/front",
            tmp_path / "folder.jpg",
            allow_redirects=True,
        )
        assert dl.width == 200
        assert (tmp_path / "folder.jpg").is_file()
