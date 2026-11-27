"""Phase 6 E2E test: fetch_subtitles and fetch_lyrics jobs with only-missing protection."""

import hashlib
from pathlib import Path

import httpx
import respx
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TRCK
from sqlalchemy import select

from metashelf.config import Settings
from metashelf.db.models import Library, SidecarFile
from metashelf.jobs.handlers import handle_fetch_lyrics, handle_fetch_subtitles
from metashelf.jobs.queue import enqueue_job
from metashelf.main import create_app
from metashelf.scanner.movie import scan_movie_library
from metashelf.scanner.music import scan_music_library
from metashelf.scanner.tv import scan_tv_library

OS_FIX = Path(__file__).parent / "fixtures" / "opensubtitles"
LRC_FIX = Path(__file__).parent / "fixtures" / "lrclib"


def _write_mp3(path: Path, title: str, artist: str, album: str, track: str) -> None:
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.write_bytes(frame * 2)
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    tags.add(TPE2(encoding=3, text=artist))
    tags.add(TALB(encoding=3, text=album))
    tags.add(TRCK(encoding=3, text=track))
    tags.save(path)


@respx.mock
async def test_phase6_fetch_subtitles_and_lyrics_never_overwrite_existing(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    movies_dir = media_root / "movies" / "Inception (2010)"
    tv_dir = media_root / "tv" / "Breaking Bad (2008)" / "Season 01"
    music_dir = media_root / "music" / "Daft Punk" / "Discovery (2001)"
    movies_dir.mkdir(parents=True)
    tv_dir.mkdir(parents=True)
    music_dir.mkdir(parents=True)

    movie_file = movies_dir / "Inception (2010).mkv"
    movie_file.write_bytes(b"movie-data")
    # Pre-existing English subtitle must NEVER be overwritten in only-missing mode
    existing_en_srt = movies_dir / "Inception (2010).en.srt"
    existing_en_srt.write_text("EXISTING EN SUBTITLE", encoding="utf-8")
    existing_en_hash = hashlib.sha256(existing_en_srt.read_bytes()).hexdigest()

    ep_file = tv_dir / "Breaking.Bad.S01E01.mkv"
    ep_file.write_bytes(b"ep-data")

    track1 = music_dir / "01 - One More Time.mp3"
    track2 = music_dir / "02 - Aerodynamic.mp3"
    _write_mp3(track1, "One More Time", "Daft Punk", "Discovery", "1/2")
    _write_mp3(track2, "Aerodynamic", "Daft Punk", "Discovery", "2/2")

    # Mock OpenSubtitles
    respx.get("https://api.opensubtitles.com/api/v1/subtitles").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "101",
                        "attributes": {
                            "language": "es",
                            "files": [{"file_id": 5274788, "file_name": "sub.es.srt"}],
                        },
                    }
                ]
            },
        )
    )
    respx.post("https://api.opensubtitles.com/api/v1/login").mock(
        return_value=httpx.Response(
            200, text=(OS_FIX / "login.json").read_text(encoding="utf-8")
        )
    )
    respx.post("https://api.opensubtitles.com/api/v1/download").mock(
        return_value=httpx.Response(
            200, text=(OS_FIX / "download_5274788.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://dl.opensubtitles.org/en/download/sub/5274788").mock(
        return_value=httpx.Response(
            200, content=b"1\n00:00:01,000 --> 00:00:02,000\nHola.\n"
        )
    )

    # Mock LRCLIB
    def _lrclib_get(request: httpx.Request) -> httpx.Response:
        if "One More Time" in request.url.params.get("track_name", ""):
            return httpx.Response(
                200, text=(LRC_FIX / "get_one_more_time.json").read_text(encoding="utf-8")
            )
        return httpx.Response(404)

    respx.get("https://lrclib.net/api/get").mock(side_effect=_lrclib_get)
    respx.get("https://lrclib.net/api/search").mock(
        return_value=httpx.Response(
            200, text=(LRC_FIX / "search_aerodynamic.json").read_text(encoding="utf-8")
        )
    )

    settings = Settings(
        config_dir=tmp_path / "config",
        media_roots=str(media_root),
        opensubtitles_api_key="os-key",
        opensubtitles_username="u",
        opensubtitles_password="p",
    )
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app), app.state.session_factory() as session:
        m_lib = Library(
            name="Movies", type="movie", root_path=str(media_root / "movies")
        )
        t_lib = Library(name="TV", type="tv", root_path=str(media_root / "tv"))
        mu_lib = Library(
            name="Music", type="music", root_path=str(media_root / "music")
        )
        session.add_all([m_lib, t_lib, mu_lib])
        await session.commit()

        await scan_movie_library(session, m_lib)
        await scan_tv_library(session, t_lib)
        await scan_music_library(session, mu_lib)

        # Fetch subtitles for movies (en, es) -> en skipped, es downloaded
        j_sub_m = await enqueue_job(
            session,
            "fetch_subtitles",
            {"library_id": m_lib.id, "languages": ["en", "es"], "only_missing": True},
        )
        await handle_fetch_subtitles(
            session,
            j_sub_m,
            {"library_id": m_lib.id, "languages": ["en", "es"], "only_missing": True},
            app.state.http_client,
            settings,
        )

        # Fetch subtitles for TV (es)
        j_sub_t = await enqueue_job(
            session,
            "fetch_subtitles",
            {"library_id": t_lib.id, "languages": ["es"], "only_missing": True},
        )
        await handle_fetch_subtitles(
            session,
            j_sub_t,
            {"library_id": t_lib.id, "languages": ["es"], "only_missing": True},
            app.state.http_client,
            settings,
        )

        # Fetch lyrics for Music
        j_lyr = await enqueue_job(
            session,
            "fetch_lyrics",
            {"library_id": mu_lib.id, "only_missing": True},
        )
        await handle_fetch_lyrics(
            session,
            j_lyr,
            {"library_id": mu_lib.id, "only_missing": True},
            app.state.http_client,
            settings,
        )

        # Verify existing .en.srt was untouched
        assert hashlib.sha256(existing_en_srt.read_bytes()).hexdigest() == existing_en_hash
        # Verify .es.srt created for movie and episode
        assert (movies_dir / "Inception (2010).es.srt").is_file()
        assert (tv_dir / "Breaking.Bad.S01E01.es.srt").is_file()
        # Verify .lrc and .txt created for tracks
        assert (music_dir / "01 - One More Time.lrc").is_file()
        assert (music_dir / "02 - Aerodynamic.txt").is_file()

        sidecars = (await session.execute(select(SidecarFile))).scalars().all()
        assert len(sidecars) == 4
