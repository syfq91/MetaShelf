"""Phase 4 E2E test: EPUB folder gets .opf/.jpg and empty DB rebuild restores metadata."""

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
from metashelf.db.models import Item, Library
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.domain.models import EbookMetadata
from metashelf.jobs.queue import enqueue_job
from metashelf.main import create_app
from metashelf.scanner.ebook import scan_ebook_library

OL_FIX = Path(__file__).parent / "fixtures" / "openlibrary"

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _make_epub(
    path: Path, title: str, authors: list[str], isbn: str, series: str, idx: str
) -> None:
    creators = "\n".join(
        f'<dc:creator id="c{i}">{a}</dc:creator>' for i, a in enumerate(authors, start=1)
    )
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">{isbn}</dc:identifier>
    <dc:title>{title}</dc:title>
    {creators}
    <meta property="belongs-to-collection" id="coll1">{series}</meta>
    <meta refines="#coll1" property="group-position">{idx}</meta>
  </metadata>
</package>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/package.opf", opf)


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
    Image.new("RGB", (200, 300), color=(100, 60, 20)).save(buf, format="JPEG")
    return buf.getvalue()


@respx.mock
async def test_phase4_ebooks_get_opf_and_cover_and_rebuild_index(tmp_path: Path) -> None:
    ebook_root = tmp_path / "ebooks"
    ebook_root.mkdir(parents=True)
    _make_epub(
        ebook_root / "Dune.epub",
        "Dune",
        ["Frank Herbert", "Brian Herbert"],
        "9780441172719",
        "Dune Chronicles",
        "1",
    )

    respx.get("https://openlibrary.org/search.json").mock(
        return_value=httpx.Response(
            200, text=(OL_FIX / "search_dune.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://openlibrary.org/isbn/9780441172719.json").mock(
        return_value=httpx.Response(
            200, text=(OL_FIX / "isbn_9780441172719.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://openlibrary.org/works/OL893415W.json").mock(
        return_value=httpx.Response(
            200, text=(OL_FIX / "work_OL893415W.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://covers.openlibrary.org/b/isbn/9780441172719-L.jpg").mock(
        return_value=httpx.Response(
            200, content=_jpeg_bytes(), headers={"content-type": "image/jpeg"}
        )
    )

    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(ebook_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        r_lib = client.post(
            "/settings/libraries",
            headers=headers,
            data={"name": "Ebooks", "lib_type": "ebook", "root_path": str(ebook_root)},
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

        assert (ebook_root / "Dune.opf").is_file()
        assert (ebook_root / "Dune.jpg").is_file()

        # Check UI renders Ebooks page with multi-author & series
        r_ui = client.get("/ebooks")
        assert r_ui.status_code == 200
        assert "Dune Chronicles" in r_ui.text
        assert "Frank Herbert, Brian Herbert" in r_ui.text

        async with app.state.session_factory() as session:
            orig_item = (await session.execute(select(Item))).scalar_one()
            orig_meta = EbookMetadata.model_validate_json(orig_item.metadata_json)

    # Rebuild index from a completely empty DB and verify identical metadata is restored
    rebuilt_db = f"sqlite+aiosqlite:///{tmp_path / 'rebuilt.db'}"
    run_migrations(rebuilt_db)
    engine2 = create_async_engine_with_wal(rebuilt_db)
    sf2 = create_session_factory(engine2)
    try:
        async with sf2() as session2:
            lib2 = Library(name="Ebooks", type="ebook", root_path=str(ebook_root))
            session2.add(lib2)
            await session2.commit()
            await scan_ebook_library(session2, lib2)
            rebuilt_item = (await session2.execute(select(Item))).scalar_one()
            rebuilt_meta = EbookMetadata.model_validate_json(rebuilt_item.metadata_json)
            assert rebuilt_meta == orig_meta
            assert rebuilt_item.state == "complete"
    finally:
        await engine2.dispose()
