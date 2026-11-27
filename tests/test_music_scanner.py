"""Tests for music artist/album/track scanner with mutagen tags (written before implementation)."""

from pathlib import Path

from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE1, TPE2, TRCK
from sqlalchemy import select

from metashelf.db.models import Artwork, Item, Library
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.scanner.music import scan_music_library


def _write_tagged_mp3(
    path: Path,
    *,
    title: str,
    artist: str,
    album: str,
    track: str,
    year: str,
) -> None:
    """Write a minimal valid MP3 frame with ID3v2 tags."""
    # Minimal MPEG1 Layer3 128kbps 44.1kHz frame (417 bytes)
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.write_bytes(frame * 2)
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    tags.add(TPE2(encoding=3, text=artist))
    tags.add(TALB(encoding=3, text=album))
    tags.add(TRCK(encoding=3, text=track))
    tags.add(TDRC(encoding=3, text=year))
    tags.save(path)


async def test_scan_music_library_with_mutagen_tags(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    run_migrations(db_url)
    engine = create_async_engine_with_wal(db_url)
    session_factory = create_session_factory(engine)

    music_root = tmp_path / "music"
    artist_dir = music_root / "Daft Punk"
    album1_dir = artist_dir / "Discovery (2001)"
    album2_dir = artist_dir / "Homework (1997)"
    album1_dir.mkdir(parents=True)
    album2_dir.mkdir(parents=True)

    _write_tagged_mp3(
        album1_dir / "01 - One More Time.mp3",
        title="One More Time",
        artist="Daft Punk",
        album="Discovery",
        track="1/14",
        year="2001",
    )
    _write_tagged_mp3(
        album1_dir / "02 - Aerodynamic.mp3",
        title="Aerodynamic",
        artist="Daft Punk",
        album="Discovery",
        track="2/14",
        year="2001",
    )
    _write_tagged_mp3(
        album2_dir / "01 - Daftendirekt.mp3",
        title="Daftendirekt",
        artist="Daft Punk",
        album="Homework",
        track="1/16",
        year="1997",
    )
    (album1_dir / "folder.jpg").write_bytes(b"album1-cover")

    try:
        async with session_factory() as session:
            lib = Library(name="Music", type="music", root_path=str(music_root))
            session.add(lib)
            await session.commit()

            stats = await scan_music_library(session, lib)
            assert stats.added == 3

            artists = (
                await session.execute(select(Item).where(Item.kind == "artist"))
            ).scalars().all()
            assert len(artists) == 1
            assert artists[0].title == "Daft Punk"

            albums = (
                await session.execute(
                    select(Item).where(Item.kind == "album").order_by(Item.rel_path)
                )
            ).scalars().all()
            assert len(albums) == 2
            assert albums[0].title == "Discovery"
            assert albums[0].year == 2001
            assert albums[1].title == "Homework"
            assert all(a.parent_id == artists[0].id for a in albums)

            tracks = (
                await session.execute(
                    select(Item).where(Item.kind == "track").order_by(Item.rel_path)
                )
            ).scalars().all()
            assert len(tracks) == 3
            assert tracks[0].title == "One More Time"

            arts = (
                await session.execute(
                    select(Artwork).where(Artwork.item_id == albums[0].id)
                )
            ).scalars().all()
            assert len(arts) == 1
            assert arts[0].type == "cover"

            # Incremental re-scan skips unchanged tracks
            stats2 = await scan_music_library(session, lib)
            assert stats2.added == 0
            assert stats2.skipped == 3
    finally:
        await engine.dispose()
