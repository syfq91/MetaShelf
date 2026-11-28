"""Tests for settings export/import and `metashelf rebuild-index` CLI."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from metashelf.cli import main as cli_main
from metashelf.config import Settings
from metashelf.db.models import Item, Library
from metashelf.main import create_app
from metashelf.scanner.movie import scan_movie_library
from metashelf.services.movie_save import save_movie_to_disk


def _setup_and_login(_client: TestClient) -> str:
    return ""


async def test_settings_export_and_import_rejects_missing_dir(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    movies_dir = media_root / "movies"
    movies_dir.mkdir(parents=True)

    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        # Add library and preference
        r_lib = client.post(
            "/settings/libraries",
            headers=headers,
            data={"name": "Movies", "lib_type": "movie", "root_path": str(movies_dir)},
        )
        assert r_lib.status_code == 200
        client.post(
            "/settings/preferences",
            headers=headers,
            data={"language": "fr-FR", "movie_naming": "folder"},
        )

        # Export
        r_exp = client.get("/settings/export")
        assert r_exp.status_code == 200
        bundle = r_exp.json()
        assert bundle["settings"]["metadata_language"] == "fr-FR"
        assert len(bundle["libraries"]) == 1
        assert bundle["libraries"][0]["name"] == "Movies"

        # Import rejecting non-existent directory
        bad_bundle = {
            "version": 1,
            "settings": {"metadata_language": "en-US"},
            "libraries": [
                {
                    "name": "Missing",
                    "type": "movie",
                    "root_path": str(tmp_path / "does_not_exist"),
                    "enabled": True,
                }
            ],
        }
        r_bad = client.post(
            "/settings/import",
            headers=headers,
            data={"payload": json.dumps(bad_bundle)},
        )
        assert r_bad.status_code == 400

        # Valid import restores settings
        bundle["settings"]["metadata_language"] = "es-ES"
        r_ok = client.post(
            "/settings/import",
            headers=headers,
            data={"payload": json.dumps(bundle)},
        )
        assert r_ok.status_code == 200
        assert "Imported" in r_ok.text

        r_exp2 = client.get("/settings/export")
        assert r_exp2.json()["settings"]["metadata_language"] == "es-ES"


def test_cli_rebuild_index_reconstructs_from_sidecars(tmp_path: Path) -> None:
    import asyncio

    media_root = tmp_path / "movies"
    m_dir = media_root / "Inception (2010)"
    m_dir.mkdir(parents=True)
    (m_dir / "Inception (2010).mkv").write_bytes(b"video")

    config_dir = tmp_path / "config"
    app_settings = Settings(config_dir=config_dir, media_roots=str(media_root))
    app = create_app(settings=app_settings)

    async def _seed() -> None:
        async with app.state.session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.commit()
            await scan_movie_library(session, lib)
            item = await session.scalar(select(Item))
            assert item is not None
            await save_movie_to_disk(session, item, lib)

    with TestClient(app):
        asyncio.run(_seed())

    # Run CLI rebuild-index
    exit_code = cli_main(
        [
            "rebuild-index",
            "--config-dir",
            str(config_dir),
        ]
    )
    assert exit_code == 0

    # Verify DB has the rebuilt item from the sidecar on disk
    async def _check() -> None:
        async with app2.state.session_factory() as session:
            items = list((await session.scalars(select(Item))).all())
            assert len(items) == 1
            assert items[0].title == "Inception"
            assert items[0].year == 2010

    app2 = create_app(settings=app_settings)
    with TestClient(app2):
        asyncio.run(_check())
