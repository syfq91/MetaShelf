"""Tests for Scrape modal search, preview, and selective field apply."""

import re
from io import BytesIO
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient
from PIL import Image

from metashelf.config import Settings
from metashelf.db.models import Library
from metashelf.main import create_app
from metashelf.scanner.movie import scan_movie_library

FIXTURES = Path(__file__).parent / "fixtures" / "tmdb"


def _setup_and_login(client: TestClient) -> str:
    resp = client.post(
        "/auth/setup",
        data={
            "username": "admin",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=True,
    )
    match = re.search(r'"X-CSRF-Token":\s*"([^"]+)"', resp.text)
    assert match is not None
    return match.group(1)


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (100, 150), color=(10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


@respx.mock
async def test_scrape_modal_search_and_apply(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    m_dir = media_root / "Inception (2010)"
    m_dir.mkdir(parents=True)
    (m_dir / "Inception (2010).mkv").write_bytes(b"video")

    respx.get("https://api.themoviedb.org/3/search/movie").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "search_inception.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/movie/27205").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "movie_27205.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/movie/27205/images").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "images_27205.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://image.tmdb.org/t/p/original/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg").mock(
        return_value=httpx.Response(
            200, content=_jpeg_bytes(), headers={"content-type": "image/jpeg"}
        )
    )

    app_settings = Settings(
        config_dir=tmp_path / "config",
        media_roots=str(media_root),
        tmdb_api_key="dummy-key",
    )
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        async with app.state.session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.commit()
            await scan_movie_library(session, lib)

        # Open modal
        r_modal = client.get("/movies/1/scrape")
        assert r_modal.status_code == 200
        assert "Inception" in r_modal.text

        # Search
        r_search = client.post(
            "/movies/1/scrape/search",
            headers=headers,
            data={"title": "Inception", "year": "2010"},
        )
        assert r_search.status_code == 200
        assert "Inception: The Cobol Job" in r_search.text

        # Preview candidate 27205
        r_prev = client.get("/movies/1/scrape/preview/27205")
        assert r_prev.status_code == 200
        assert "Fields to apply" in r_prev.text

        # Apply selective fields (title, plot, poster)
        r_apply = client.post(
            "/movies/1/scrape/apply",
            headers=headers,
            data={
                "provider_id": "27205",
                "fields": ["title", "plot", "poster"],
                "poster_url": "https://image.tmdb.org/t/p/original/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
                "fanart_url": "",
            },
        )
        assert r_apply.status_code == 200
        assert "Your mind is the scene of the crime." in r_apply.text
        assert (m_dir / "Inception (2010)-poster.jpg").is_file()
