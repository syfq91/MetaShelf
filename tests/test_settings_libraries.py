"""Tests for library CRUD in Settings and path confinement."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.main import create_app


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


def test_library_crud_and_path_confinement(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    movies_dir = media_root / "movies"
    movies_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True)

    app_settings = Settings(
        config_dir=tmp_path / "config",
        media_roots=str(media_root),
    )
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        # Path outside media_roots is rejected
        bad = client.post(
            "/settings/libraries",
            headers=headers,
            data={
                "name": "Escape",
                "lib_type": "movie",
                "root_path": str(outside_dir),
            },
        )
        assert bad.status_code == 400
        assert "outside configured media roots" in bad.text

        # Path traversal in dir-picker is rejected
        picker_bad = client.get(f"/settings/dir-picker?path={outside_dir}")
        assert "outside configured media roots" in picker_bad.text

        # Valid dir-picker lists movies_dir
        picker_ok = client.get(f"/settings/dir-picker?path={media_root}")
        assert "movies" in picker_ok.text

        # Create library inside media_root
        ok = client.post(
            "/settings/libraries",
            headers=headers,
            data={
                "name": "My Movies",
                "lib_type": "movie",
                "root_path": str(movies_dir),
            },
        )
        assert ok.status_code == 200
        assert "My Movies" in ok.text
        assert str(movies_dir.resolve()) in ok.text

        # Toggle library
        toggle = client.post("/settings/libraries/1/toggle", headers=headers)
        assert toggle.status_code == 200
        assert "Disabled" in toggle.text

        # Delete library
        deleted = client.delete("/settings/libraries/1", headers=headers)
        assert deleted.status_code == 200
        assert "No libraries configured yet" in deleted.text
