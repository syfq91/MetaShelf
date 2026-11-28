"""Tests for Movies two-pane UI, edit, save, and revert."""

from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.db.models import Library
from metashelf.main import create_app
from metashelf.scanner.movie import scan_movie_library


def _setup_and_login(_client: TestClient) -> str:
    return ""


async def test_movies_view_edit_save_revert(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    m_dir = media_root / "Inception (2010)"
    m_dir.mkdir(parents=True)
    (m_dir / "Inception (2010).mkv").write_bytes(b"video")

    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        # Seed library and scan
        async with app.state.session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.commit()
            await scan_movie_library(session, lib)

        # List & detail view
        r = client.get("/movies")
        assert r.status_code == 200
        assert "Inception" in r.text

        # Edit -> dirty
        r_edit = client.post(
            "/movies/1/edit",
            headers=headers,
            data={"title": "Inception Edited", "year": "2010", "plot": "Dream heist."},
        )
        assert r_edit.status_code == 200
        assert "dirty" in r_edit.text
        assert "Inception Edited" in r_edit.text

        # Save -> writes NFO
        r_save = client.post("/movies/1/save", headers=headers)
        assert r_save.status_code == 200
        nfo_file = m_dir / "Inception (2010).nfo"
        assert nfo_file.is_file()
        assert "<title>Inception Edited</title>" in nfo_file.read_text(encoding="utf-8")

        # Edit again -> dirty, then Revert -> restores saved NFO
        client.post(
            "/movies/1/edit",
            headers=headers,
            data={"title": "Discard Me", "year": "2010"},
        )
        r_rev = client.post("/movies/1/revert", headers=headers)
        assert r_rev.status_code == 200
        assert "Inception Edited" in r_rev.text
        assert "Discard Me" not in r_rev.text
