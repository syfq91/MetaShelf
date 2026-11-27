"""Tests for CBZ comic scanner and embedded ComicInfo.xml adoption (written first)."""

import zipfile
from pathlib import Path

from sqlalchemy import select

from metashelf.db.models import Item, Library
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.domain.models import ComicMetadata
from metashelf.scanner.comic import scan_comic_library

EMBEDDED_COMICINFO = """<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Title>Court of Owls</Title>
  <Series>Batman</Series>
  <Number>1</Number>
  <Volume>2</Volume>
  <Year>2011</Year>
  <Publisher>DC Comics</Publisher>
  <Writer>Scott Snyder</Writer>
  <Penciller>Greg Capullo</Penciller>
  <Summary>Bruce Wayne faces the Court of Owls.</Summary>
</ComicInfo>
"""

SIDECAR_COMICINFO = """<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Title>Sidecar Wins Title</Title>
  <Series>Batman</Series>
  <Number>1</Number>
  <Year>2011</Year>
  <Publisher>DC Comics</Publisher>
</ComicInfo>
"""


def _make_cbz(path: Path, embedded_xml: str | None = None) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("001.jpg", b"fake-page-1")
        if embedded_xml:
            zf.writestr("ComicInfo.xml", embedded_xml)


async def test_scan_comic_library_embedded_and_sidecar_priority(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    run_migrations(db_url)
    engine = create_async_engine_with_wal(db_url)
    session_factory = create_session_factory(engine)

    comic_root = tmp_path / "comics"
    series_dir = comic_root / "Batman"
    series_dir.mkdir(parents=True)

    cbz1 = series_dir / "Batman #001 (2011).cbz"
    _make_cbz(cbz1, embedded_xml=EMBEDDED_COMICINFO)

    cbz2 = series_dir / "Batman #002 (2011).cbz"
    _make_cbz(cbz2, embedded_xml=EMBEDDED_COMICINFO)
    (series_dir / "Batman #002 (2011).xml").write_text(SIDECAR_COMICINFO, encoding="utf-8")

    try:
        async with session_factory() as session:
            lib = Library(name="Comics", type="comic", root_path=str(comic_root))
            session.add(lib)
            await session.commit()

            stats = await scan_comic_library(session, lib)
            assert stats.added == 2

            items = (
                await session.execute(select(Item).order_by(Item.rel_path))
            ).scalars().all()
            assert len(items) == 2

            m1 = ComicMetadata.model_validate_json(items[0].metadata_json)
            assert m1.title == "Court of Owls"
            assert m1.writers == ["Scott Snyder"]
            assert m1.artists == ["Greg Capullo"]

            # Sidecar .xml wins over embedded ComicInfo.xml
            m2 = ComicMetadata.model_validate_json(items[1].metadata_json)
            assert m2.title == "Sidecar Wins Title"

            # Incremental skip
            stats2 = await scan_comic_library(session, lib)
            assert stats2.added == 0
            assert stats2.skipped == 2
    finally:
        await engine.dispose()
