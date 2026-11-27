"""Phase 1 E2E test: 20-movie library scan, auto-match with TMDB fixtures, UI edit, and save."""

import re
from io import BytesIO
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from metashelf.config import Settings
from metashelf.db.models import Item, Library
from metashelf.jobs.queue import enqueue_job
from metashelf.main import create_app
from metashelf.readers.kodi_nfo_movie import read_movie_nfo

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
    Image.new("RGB", (100, 150), color=(30, 60, 90)).save(buf, format="JPEG")
    return buf.getvalue()


@respx.mock
async def test_phase1_20_movies_scan_automatch_edit_save(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    media_root.mkdir(parents=True)

    # Create 20 movie folders
    for idx in range(1, 21):
        name = f"Inception {idx:02d} (2010)" if idx > 1 else "Inception (2010)"
        folder = media_root / name
        folder.mkdir(parents=True)
        (folder / f"{name}.mkv").write_bytes(b"video-data")

    # Mock TMDB responses for all 20 movies
    search_json = (FIXTURES / "search_inception.json").read_text(encoding="utf-8")
    details_json = (FIXTURES / "movie_27205.json").read_text(encoding="utf-8")
    images_json = (FIXTURES / "images_27205.json").read_text(encoding="utf-8")
    img_bytes = _jpeg_bytes()

    respx.get("https://api.themoviedb.org/3/search/movie").mock(
        return_value=httpx.Response(200, text=search_json)
    )
    respx.get("https://api.themoviedb.org/3/movie/27205").mock(
        return_value=httpx.Response(200, text=details_json)
    )
    respx.get("https://api.themoviedb.org/3/movie/27205/images").mock(
        return_value=httpx.Response(200, text=images_json)
    )
    respx.get(url__startswith="https://image.tmdb.org/t/p/original/").mock(
        return_value=httpx.Response(
            200, content=img_bytes, headers={"content-type": "image/jpeg"}
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

        # 1. Add library via Settings
        r_lib = client.post(
            "/settings/libraries",
            headers=headers,
            data={"name": "Movies", "lib_type": "movie", "root_path": str(media_root)},
        )
        assert r_lib.status_code == 200

        # 2. Enqueue and run scan_library job
        async with app.state.session_factory() as session:
            lib = (await session.execute(select(Library))).scalar_one()
            await enqueue_job(session, "scan_library", {"library_id": lib.id})
        await app.state.job_worker.run_one_pending()

        async with app.state.session_factory() as session:
            items = (await session.execute(select(Item))).scalars().all()
            assert len(items) == 20

        # 3. Enqueue and run auto_match job
        async with app.state.session_factory() as session:
            lib = (await session.execute(select(Library))).scalar_one()
            await enqueue_job(session, "auto_match", {"library_id": lib.id})
        await app.state.job_worker.run_one_pending()

        # Verify first movie ("Inception (2010)") was auto-matched & saved with NFO + poster
        nfo_path = media_root / "Inception (2010)" / "Inception (2010).nfo"
        poster_path = media_root / "Inception (2010)" / "Inception (2010)-poster.jpg"
        assert nfo_path.is_file()
        assert poster_path.is_file()

        # 4. Edit in UI and Save
        async with app.state.session_factory() as session:
            first_item = (
                await session.execute(
                    select(Item).where(Item.rel_path == "Inception (2010)/Inception (2010).mkv")
                )
            ).scalar_one()
            item_id = first_item.id

        r_edit = client.post(
            f"/movies/{item_id}/edit",
            headers=headers,
            data={
                "title": "Inception",
                "year": "2010",
                "tagline": "Custom Edited Tagline",
                "plot": "Custom plot.",
            },
        )
        assert r_edit.status_code == 200

        r_save = client.post(f"/movies/{item_id}/save", headers=headers)
        assert r_save.status_code == 200

        parsed_nfo = read_movie_nfo(nfo_path)
        assert parsed_nfo.metadata.tagline == "Custom Edited Tagline"
        assert parsed_nfo.metadata.tmdb_id == "27205"
        assert (media_root / "Inception (2010)" / "Inception (2010).nfo.bak").is_file()
