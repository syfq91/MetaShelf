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


def test_library_crud_and_dir_picker(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    movies_dir = media_root / "movies"
    movies_dir.mkdir(parents=True)
    other_dir = tmp_path / "other"
    other_dir.mkdir(parents=True)
    missing_dir = tmp_path / "does_not_exist"

    app_settings = Settings(config_dir=tmp_path / "config")
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        # Non-existent directory is rejected
        bad = client.post(
            "/settings/libraries",
            headers=headers,
            data={
                "name": "Missing",
                "lib_type": "movie",
                "root_path": str(missing_dir),
            },
        )
        assert bad.status_code == 400
        assert "Directory does not exist" in bad.text

        # Non-existent directory in dir-picker shows error
        picker_bad = client.get(f"/settings/dir-picker?path={missing_dir}")
        assert "Directory" in picker_bad.text
        assert "does not exist" in picker_bad.text

        # Default dir-picker loads without error
        picker_default = client.get("/settings/dir-picker")
        assert picker_default.status_code == 200

        # Valid dir-picker lists movies_dir and allows navigating to other_dir
        picker_ok = client.get(f"/settings/dir-picker?path={media_root}")
        assert "movies" in picker_ok.text
        picker_other = client.get(f"/settings/dir-picker?path={other_dir}")
        assert picker_other.status_code == 200

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
