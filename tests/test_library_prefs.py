"""Tests for per-library preferences storage and Settings UI."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.db.models import Library
from metashelf.main import create_app
from metashelf.services.library_prefs import (
    LibraryPreferences,
    get_library_prefs,
    set_library_prefs,
)


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


async def test_library_prefs_service_and_routes(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    media_root.mkdir()
    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        async with app.state.session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.commit()
            lib_id = lib.id

            # Defaults
            defaults = await get_library_prefs(session, lib_id)
            assert defaults.naming_scheme == "file"
            assert defaults.language == "en-US"
            assert defaults.max_posters == 3
            assert defaults.max_fanart == 3

            # Direct update
            await set_library_prefs(
                session,
                lib_id,
                LibraryPreferences(
                    naming_scheme="movie_nfo",
                    language="ja-JP",
                    max_posters=5,
                    max_fanart=2,
                ),
            )
            loaded = await get_library_prefs(session, lib_id)
            assert loaded.naming_scheme == "movie_nfo"
            assert loaded.language == "ja-JP"
            assert loaded.max_posters == 5
            assert loaded.max_fanart == 2

        # GET form
        r_get = client.get(f"/settings/libraries/{lib_id}/prefs")
        assert r_get.status_code == 200
        assert "ja-JP" in r_get.text

        # POST update via route
        r_post = client.post(
            f"/settings/libraries/{lib_id}/prefs",
            headers=headers,
            data={
                "naming_scheme": "file",
                "language": "de-DE",
                "max_posters": "8",
                "max_fanart": "4",
            },
        )
        assert r_post.status_code == 200
        assert "Saved" in r_post.text
        assert "de-DE" in r_post.text

        async with app.state.session_factory() as session:
            after = await get_library_prefs(session, lib_id)
            assert after.naming_scheme == "file"
            assert after.language == "de-DE"
            assert after.max_posters == 8
            assert after.max_fanart == 4
