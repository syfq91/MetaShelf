"""Security hardening tests: path traversal, SSRF, image validation, and rate limits."""

import re
from io import BytesIO
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from PIL import Image

from metashelf.config import Settings
from metashelf.main import create_app
from metashelf.services.paths import PathTraversalError, resolve_within_root
from metashelf.writers.artwork import (
    MAX_ARTWORK_BYTES,
    ArtworkDownloadError,
    download_artwork,
    validate_artwork_url,
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


def _make_png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_path_traversal_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(PathTraversalError):
        resolve_within_root("../secret.txt", root)

    symlink_path = root / "escape.txt"
    symlink_path.symlink_to(outside)
    with pytest.raises(PathTraversalError):
        resolve_within_root("escape.txt", root)


def test_http_routes_reject_invalid_library_paths(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    not_a_dir = tmp_path / "not_a_dir.txt"
    not_a_dir.write_text("file", encoding="utf-8")
    missing_dir = tmp_path / "missing"
    app_settings = Settings(config_dir=tmp_path / "config")
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        r_missing = client.post(
            "/settings/libraries",
            headers=headers,
            data={"name": "Missing", "lib_type": "movie", "root_path": str(missing_dir)},
        )
        assert r_missing.status_code == 400

        r_file = client.post(
            "/settings/libraries",
            headers=headers,
            data={"name": "File", "lib_type": "movie", "root_path": str(not_a_dir)},
        )
        assert r_file.status_code == 400

        r_browse = client.get("/settings/dir-picker", params={"path": str(missing_dir)})
        assert r_browse.status_code == 200
        assert "does not exist" in r_browse.text


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "ftp://example.com/poster.jpg",
        "http://localhost/poster.jpg",
        "http://sub.local/poster.jpg",
        "http://127.0.0.1/poster.jpg",
        "http://0.0.0.0/poster.jpg",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/poster.jpg",
        "http://192.168.1.10/poster.jpg",
        "http://[::1]/poster.jpg",
    ],
)
def test_ssrf_artwork_url_rejected(bad_url: str) -> None:
    with pytest.raises(ArtworkDownloadError):
        validate_artwork_url(bad_url)


@respx.mock
async def test_artwork_download_rejects_redirect_to_private_bad_type_oversize_and_corrupt(
    tmp_path: Path,
) -> None:
    target = tmp_path / "poster.jpg"

    # Redirect to private IP
    respx.get("https://cdn.example.com/redir.jpg").mock(
        return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1/secret.jpg"})
    )
    respx.get("http://127.0.0.1/secret.jpg").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "image/png"}, content=_make_png_bytes()
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArtworkDownloadError):
            await download_artwork(
                client,
                "https://cdn.example.com/redir.jpg",
                target,
                allow_redirects=True,
            )

    # Wrong content-type
    respx.get("https://cdn.example.com/html").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<h1>hi</h1>"
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArtworkDownloadError):
            await download_artwork(client, "https://cdn.example.com/html", target)

    # Corrupt image payload
    respx.get("https://cdn.example.com/corrupt.png").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "image/png"}, content=b"not-a-png"
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArtworkDownloadError):
            await download_artwork(client, "https://cdn.example.com/corrupt.png", target)

    # Oversize payload
    respx.get("https://cdn.example.com/huge.png").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"0" * (MAX_ARTWORK_BYTES + 1),
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArtworkDownloadError):
            await download_artwork(client, "https://cdn.example.com/huge.png", target)

    # Valid PNG succeeds
    respx.get("https://cdn.example.com/ok.png").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "image/png"}, content=_make_png_bytes()
        )
    )
    async with httpx.AsyncClient() as client:
        downloaded = await download_artwork(client, "https://cdn.example.com/ok.png", target)
        assert downloaded.width == 4
        assert downloaded.height == 4
        assert target.exists()


def test_login_rate_limit_enforced(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        client.post(
            "/auth/setup",
            data={
                "username": "admin",
                "password": "password123",
                "password_confirm": "password123",
            },
        )
        client.cookies.clear()

        statuses = []
        for _ in range(12):
            resp = client.post(
                "/auth/login",
                data={"username": "admin", "password": "wrong-password"},
            )
            statuses.append(resp.status_code)
        assert 429 in statuses


def test_secret_key_auto_generated_and_persisted(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    config_dir = tmp_path / "config"

    app1 = create_app(settings=Settings(config_dir=config_dir, media_roots=str(media_root)))
    with TestClient(app1):
        first_key = app1.state.settings.secret_key
        assert len(first_key) >= 32
        assert (config_dir / ".secret_key").read_text(encoding="utf-8").strip() == first_key

    # Second startup reuses the persisted key
    app2 = create_app(settings=Settings(config_dir=config_dir, media_roots=str(media_root)))
    with TestClient(app2):
        assert app2.state.settings.secret_key == first_key

    # Explicit key overrides auto-generation
    app3 = create_app(
        settings=Settings(
            config_dir=config_dir,
            media_roots=str(media_root),
            secret_key="explicit-user-secret",
        )
    )
    with TestClient(app3):
        assert app3.state.settings.secret_key == "explicit-user-secret"
