"""Tests for EPUB scanner and embedded OPF prefill (written before implementation)."""

import zipfile
from pathlib import Path

from sqlalchemy import select

from metashelf.db.models import Item, Library
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.domain.models import EbookMetadata
from metashelf.scanner.ebook import scan_ebook_library

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

EMBEDDED_OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">9780441172719</dc:identifier>
    <dc:title>Dune</dc:title>
    <dc:creator id="c1">Frank Herbert</dc:creator>
    <dc:language>en</dc:language>
    <dc:publisher>Chilton Books</dc:publisher>
    <dc:date>1965-08-01</dc:date>
    <dc:description>Desert planet Arrakis.</dc:description>
    <meta property="belongs-to-collection" id="coll1">Dune Chronicles</meta>
    <meta refines="#coll1" property="group-position">1</meta>
  </metadata>
  <manifest/>
  <spine/>
</package>
"""


def _create_test_epub(path: Path, opf_xml: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/package.opf", opf_xml)


async def test_scan_ebook_library_reads_embedded_opf_and_sidecar(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    run_migrations(db_url)
    engine = create_async_engine_with_wal(db_url)
    session_factory = create_session_factory(engine)

    ebook_root = tmp_path / "ebooks"
    ebook_root.mkdir(parents=True)
    epub_path = ebook_root / "Dune.epub"
    _create_test_epub(epub_path, EMBEDDED_OPF)
    (ebook_root / "Dune.jpg").write_bytes(b"fake-cover")

    try:
        async with session_factory() as session:
            lib = Library(name="Ebooks", type="ebook", root_path=str(ebook_root))
            session.add(lib)
            await session.commit()

            stats = await scan_ebook_library(session, lib)
            assert stats.added == 1

            item = (await session.execute(select(Item))).scalar_one()
            assert item.kind == "ebook"
            assert item.title == "Dune"
            assert item.year == 1965

            meta = EbookMetadata.model_validate_json(item.metadata_json)
            assert meta.authors == ["Frank Herbert"]
            assert meta.isbn == "9780441172719"
            assert meta.series == "Dune Chronicles"
            assert meta.series_index == "1"

            # Re-scan skips unchanged
            stats2 = await scan_ebook_library(session, lib)
            assert stats2.added == 0
            assert stats2.skipped == 1
    finally:
        await engine.dispose()
