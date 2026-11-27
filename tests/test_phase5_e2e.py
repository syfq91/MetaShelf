"""Phase 5 E2E test: CBZ series matched via Comic Vine -> .xml + .jpg, CBZ untouched."""

import hashlib
import re
import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from metashelf.config import Settings
from metashelf.db.models import Library
from metashelf.jobs.queue import enqueue_job
from metashelf.main import create_app
from metashelf.readers.comicinfo_xml import read_comicinfo_file

CV_FIX = Path(__file__).parent / "fixtures" / "comicvine"


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
    Image.new("RGB", (180, 260), color=(40, 40, 40)).save(buf, format="JPEG")
    return buf.getvalue()


def _make_cbz(path: Path) -> bytes:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("001.jpg", _jpeg_bytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


@respx.mock
async def test_phase5_cbz_series_matched_to_comicvine_leaves_archives_untouched(
    tmp_path: Path,
) -> None:
    comic_root = tmp_path / "comics"
    series_dir = comic_root / "Batman"
    series_dir.mkdir(parents=True)

    cbz1 = series_dir / "Batman #001 (2016).cbz"
    cbz2 = series_dir / "Batman #002 (2016).cbz"
    sha1 = _make_cbz(cbz1)
    sha2 = _make_cbz(cbz2)

    respx.get("https://comicvine.gamespot.com/api/search/").mock(
        return_value=httpx.Response(
            200, text=(CV_FIX / "search_volume_batman.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://comicvine.gamespot.com/api/issues/").mock(
        return_value=httpx.Response(
            200, text=(CV_FIX / "volume_91273_issues.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://comicvine.gamespot.com/api/issue/4000-532724/").mock(
        return_value=httpx.Response(
            200, text=(CV_FIX / "issue_532724.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://comicvine.gamespot.com/api/issue/4000-534001/").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": "OK",
                "status_code": 1,
                "results": {
                    "id": 534001,
                    "issue_number": "2",
                    "name": "I Am Gotham, Part 2",
                    "cover_date": "2016-09-01",
                    "description": "<p>Gotham and Gotham Girl arrive.</p>",
                    "volume": {"id": 91273, "name": "Batman"},
                    "person_credits": [{"name": "Tom King", "role": "writer"}],
                    "image": {
                        "super_url": "https://comicvine.gamespot.com/a/uploads/original/batman_2.jpg"
                    },
                },
            },
        )
    )
    respx.get(url__startswith="https://comicvine.gamespot.com/a/uploads/").mock(
        return_value=httpx.Response(
            200, content=_jpeg_bytes(), headers={"content-type": "image/jpeg"}
        )
    )

    app_settings = Settings(
        config_dir=tmp_path / "config",
        media_roots=str(comic_root),
        comicvine_api_key="cv-key",
    )
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        r_lib = client.post(
            "/settings/libraries",
            headers=headers,
            data={"name": "Comics", "lib_type": "comic", "root_path": str(comic_root)},
        )
        assert r_lib.status_code == 200

        async with app.state.session_factory() as session:
            lib = (await session.execute(select(Library))).scalar_one()
            await enqueue_job(session, "scan_library", {"library_id": lib.id})
        await app.state.job_worker.run_one_pending()

        async with app.state.session_factory() as session:
            lib = (await session.execute(select(Library))).scalar_one()
            await enqueue_job(session, "auto_match", {"library_id": lib.id})
        await app.state.job_worker.run_one_pending()

        # Verify .xml and .jpg created beside each CBZ
        xml1 = series_dir / "Batman #001 (2016).xml"
        jpg1 = series_dir / "Batman #001 (2016).jpg"
        xml2 = series_dir / "Batman #002 (2016).xml"
        jpg2 = series_dir / "Batman #002 (2016).jpg"
        assert xml1.is_file() and jpg1.is_file()
        assert xml2.is_file() and jpg2.is_file()

        # Archives are completely untouched
        assert hashlib.sha256(cbz1.read_bytes()).hexdigest() == sha1
        assert hashlib.sha256(cbz2.read_bytes()).hexdigest() == sha2

        parsed1 = read_comicinfo_file(xml1)
        assert parsed1.metadata.title == "I Am Gotham, Part 1"
        assert parsed1.metadata.writers == ["Tom King"]
        assert parsed1.metadata.publisher == "DC Comics"

        # Verify Comics UI groups by series and shows issue fields
        r_ui = client.get("/comics")
        assert r_ui.status_code == 200
        assert "Batman" in r_ui.text
        assert "I Am Gotham, Part 1" in r_ui.text
        assert "Tom King" in r_ui.text
