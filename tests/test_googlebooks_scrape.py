"""Tests for manual Google Books search & apply on Ebooks and Comics."""

import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient
from PIL import Image

from metashelf.config import Settings
from metashelf.domain.models import ComicMetadata, EbookMetadata, ItemKind, LibraryType
from metashelf.main import create_app


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (60, 90), color=(30, 60, 120)).save(buf, format="PNG")
    return buf.getvalue()


def _make_cbz(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("001.png", _png_bytes())


def _make_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            "<rootfiles>"
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>Local Book</dc:title>"
            "<dc:creator>Local Author</dc:creator>"
            "</metadata></package>",
        )


@respx.mock
def test_ebook_and_comic_google_books_search_and_apply(tmp_path: Path) -> None:
    ebooks_dir = tmp_path / "ebooks"
    ebooks_dir.mkdir()
    _make_epub(ebooks_dir / "Local Book.epub")

    comics_dir = tmp_path / "comics" / "Saga"
    comics_dir.mkdir(parents=True)
    _make_cbz(comics_dir / "Saga #01.cbz")

    gb_search_payload = {
        "items": [
            {
                "id": "gb-vol-1",
                "volumeInfo": {
                    "title": "Dune",
                    "authors": ["Frank Herbert"],
                    "publishedDate": "1965-08-01",
                    "publisher": "Chilton Books",
                    "description": "Desert planet epic.",
                    "categories": ["Science Fiction"],
                    "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780441172719"}],
                    "imageLinks": {"thumbnail": "https://books.example.com/cover.png"},
                },
            }
        ]
    }
    gb_volume_payload = gb_search_payload["items"][0]

    respx.get("https://www.googleapis.com/books/v1/volumes").mock(
        return_value=httpx.Response(200, json=gb_search_payload)
    )
    respx.get("https://www.googleapis.com/books/v1/volumes/gb-vol-1").mock(
        return_value=httpx.Response(200, json=gb_volume_payload)
    )
    respx.get("https://books.example.com/cover.png").mock(
        return_value=httpx.Response(
            200,
            content=_png_bytes(),
            headers={"content-type": "image/png"},
        )
    )

    app = create_app(settings=Settings(config_dir=tmp_path / "config"))
    with TestClient(app) as client:
        # Create and scan ebook library
        assert (
            client.post(
                "/settings/libraries",
                data={
                    "name": "Books",
                    "lib_type": LibraryType.EBOOK.value,
                    "root_path": str(ebooks_dir),
                },
            ).status_code
            == 200
        )
        # Create and scan comic library
        assert (
            client.post(
                "/settings/libraries",
                data={
                    "name": "Comics",
                    "lib_type": LibraryType.COMIC.value,
                    "root_path": str(tmp_path / "comics"),
                },
            ).status_code
            == 200
        )

        # Seed items via scanner directly
        import asyncio

        from sqlalchemy import select

        from metashelf.db.models import Item, Library
        from metashelf.scanner.comic import scan_comic_library
        from metashelf.scanner.ebook import scan_ebook_library

        async def _scan() -> tuple[int, int]:
            async with app.state.session_factory() as session:
                libs = list((await session.scalars(select(Library))).all())
                for lib in libs:
                    if lib.type == LibraryType.EBOOK.value:
                        await scan_ebook_library(session, lib)
                    else:
                        await scan_comic_library(session, lib)
                ebook = await session.scalar(select(Item).where(Item.kind == ItemKind.EBOOK.value))
                comic = await session.scalar(select(Item).where(Item.kind == ItemKind.COMIC.value))
                assert ebook is not None and comic is not None
                return ebook.id, comic.id

        ebook_id, comic_id = asyncio.run(_scan())

        # Ebook modal + search + apply
        r_modal = client.get(f"/ebooks/{ebook_id}/scrape")
        assert r_modal.status_code == 200
        assert "Search Google Books (Ebook)" in r_modal.text

        r_search = client.post(
            f"/ebooks/{ebook_id}/scrape/search",
            data={"title": "Dune", "author": "", "isbn": ""},
        )
        assert r_search.status_code == 200
        assert "Frank Herbert" in r_search.text
        assert "9780441172719" in r_search.text

        r_apply = client.post(
            f"/ebooks/{ebook_id}/scrape/apply",
            data={"provider_id": "gb-vol-1"},
        )
        assert r_apply.status_code == 200
        assert "Applied Google Books metadata" in r_apply.text
        assert "Dune" in r_apply.text

        # Comic modal + search + apply
        r_cmodal = client.get(f"/comics/{comic_id}/scrape")
        assert r_cmodal.status_code == 200
        assert "Search Google Books (Comic)" in r_cmodal.text

        r_csearch = client.post(
            f"/comics/{comic_id}/scrape/search",
            data={"title": "Dune", "author": ""},
        )
        assert r_csearch.status_code == 200
        assert "Dune" in r_csearch.text

        r_capply = client.post(
            f"/comics/{comic_id}/scrape/apply",
            data={"provider_id": "gb-vol-1"},
        )
        assert r_capply.status_code == 200
        assert "Applied Google Books metadata" in r_capply.text

        async def _verify_db() -> None:
            async with app.state.session_factory() as session:
                eb = await session.get(Item, ebook_id)
                cm = await session.get(Item, comic_id)
                assert eb is not None and cm is not None
                eb_meta = EbookMetadata.model_validate_json(eb.metadata_json)
                cm_meta = ComicMetadata.model_validate_json(cm.metadata_json)
                assert eb_meta.isbn == "9780441172719"
                assert cm_meta.publisher == "Chilton Books"
                assert cm_meta.writers == ["Frank Herbert"]

        asyncio.run(_verify_db())
