"""Phase 3 E2E test: artist folder with two albums gets artist.nfo, album.nfo, and folder.jpg."""

import re
from io import BytesIO
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient
from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE1, TPE2, TRCK
from PIL import Image
from sqlalchemy import select

from metashelf.config import Settings
from metashelf.db.models import Library
from metashelf.jobs.queue import enqueue_job
from metashelf.main import create_app
from metashelf.readers.kodi_nfo_music import read_album_nfo, read_artist_nfo

MB_FIX = Path(__file__).parent / "fixtures" / "musicbrainz"
CAA_FIX = Path(__file__).parent / "fixtures" / "coverart"


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


def _write_mp3(path: Path, title: str, artist: str, album: str, track: str, year: str) -> None:
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


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (200, 200), color=(30, 30, 90)).save(buf, format="JPEG")
    return buf.getvalue()


@respx.mock
async def test_phase3_artist_with_two_albums_gets_nfos_and_covers(tmp_path: Path) -> None:
    music_root = tmp_path / "music"
    artist_dir = music_root / "Daft Punk"
    alb1_dir = artist_dir / "Discovery (2001)"
    alb2_dir = artist_dir / "Homework (1997)"
    alb1_dir.mkdir(parents=True)
    alb2_dir.mkdir(parents=True)

    _write_mp3(
        alb1_dir / "01 - One More Time.mp3",
        "One More Time",
        "Daft Punk",
        "Discovery",
        "1/2",
        "2001",
    )
    _write_mp3(
        alb1_dir / "02 - Aerodynamic.mp3",
        "Aerodynamic",
        "Daft Punk",
        "Discovery",
        "2/2",
        "2001",
    )
    _write_mp3(
        alb2_dir / "01 - Daftendirekt.mp3",
        "Daftendirekt",
        "Daft Punk",
        "Homework",
        "1/1",
        "1997",
    )

    respx.get("https://musicbrainz.org/ws/2/artist").mock(
        return_value=httpx.Response(
            200, text=(MB_FIX / "search_artist_daft_punk.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://musicbrainz.org/ws/2/artist/056e4f3e-d505-4dad-8ec1-d04f521cbb56"
    ).mock(
        return_value=httpx.Response(
            200, text=(MB_FIX / "artist_daft_punk.json").read_text(encoding="utf-8")
        )
    )

    # Return Discovery vs Homework release search based on query param
    def _release_search_handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params.get("query", "")
        if "Homework" in q:
            return httpx.Response(
                200,
                json={
                    "releases": [
                        {
                            "id": "rel-homework-1",
                            "title": "Homework",
                            "date": "1997-01-20",
                            "country": "FR",
                            "track-count": 1,
                            "release-group": {"id": "rg-homework", "primary-type": "Album"},
                            "artist-credit": [
                                {
                                    "name": "Daft Punk",
                                    "artist": {"id": "056e4f3e-d505-4dad-8ec1-d04f521cbb56"},
                                }
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "releases": [
                    {
                        "id": "rel-discovery-14",
                        "title": "Discovery",
                        "date": "2001-03-12",
                        "country": "FR",
                        "track-count": 2,
                        "release-group": {"id": "rg-discovery", "primary-type": "Album"},
                        "artist-credit": [
                            {
                                "name": "Daft Punk",
                                "artist": {"id": "056e4f3e-d505-4dad-8ec1-d04f521cbb56"},
                            }
                        ],
                    },
                    {
                        "id": "rel-discovery-15",
                        "title": "Discovery",
                        "date": "2001-03-12",
                        "country": "JP",
                        "track-count": 15,
                        "release-group": {"id": "rg-discovery", "primary-type": "Album"},
                        "artist-credit": [
                            {
                                "name": "Daft Punk",
                                "artist": {"id": "056e4f3e-d505-4dad-8ec1-d04f521cbb56"},
                            }
                        ],
                    },
                ]
            },
        )

    respx.get("https://musicbrainz.org/ws/2/release").mock(side_effect=_release_search_handler)
    respx.get("https://musicbrainz.org/ws/2/release/rel-discovery-14").mock(
        return_value=httpx.Response(
            200, text=(MB_FIX / "release_discovery_14.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://musicbrainz.org/ws/2/release/rel-homework-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "rel-homework-1",
                "title": "Homework",
                "date": "1997-01-20",
                "release-group": {"id": "rg-homework", "primary-type": "Album"},
                "artist-credit": [
                    {
                        "name": "Daft Punk",
                        "artist": {"id": "056e4f3e-d505-4dad-8ec1-d04f521cbb56"},
                    }
                ],
                "label-info": [{"label": {"name": "Soma"}}],
                "tags": [{"name": "house", "count": 10}],
                "media": [
                    {
                        "position": 1,
                        "tracks": [{"position": 1, "title": "Daftendirekt", "length": 164000}],
                    }
                ],
            },
        )
    )
    respx.get("https://coverartarchive.org/release/rel-discovery-14").mock(
        return_value=httpx.Response(
            200, text=(CAA_FIX / "release_discovery.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://coverartarchive.org/release/rel-homework-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "images": [
                    {
                        "types": ["Front"],
                        "front": True,
                        "image": "https://archive.org/download/mbid-rel-homework-1/front.jpg",
                    }
                ]
            },
        )
    )
    respx.get(url__startswith="https://archive.org/download/").mock(
        return_value=httpx.Response(
            200, content=_jpeg_bytes(), headers={"content-type": "image/jpeg"}
        )
    )

    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(music_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        # 1. Create Music library & scan
        r_lib = client.post(
            "/settings/libraries",
            headers=headers,
            data={"name": "Music", "lib_type": "music", "root_path": str(music_root)},
        )
        assert r_lib.status_code == 200

        async with app.state.session_factory() as session:
            lib = (await session.execute(select(Library))).scalar_one()
            await enqueue_job(session, "scan_library", {"library_id": lib.id})
        await app.state.job_worker.run_one_pending()

        # 2. Enqueue & run auto_match_music
        async with app.state.session_factory() as session:
            lib = (await session.execute(select(Library))).scalar_one()
            await enqueue_job(session, "auto_match", {"library_id": lib.id})
        await app.state.job_worker.run_one_pending()

        # 3. Verify artist.nfo, both album.nfos, and both folder.jpg covers
        assert (artist_dir / "artist.nfo").is_file()
        assert (alb1_dir / "album.nfo").is_file()
        assert (alb1_dir / "folder.jpg").is_file()
        assert (alb2_dir / "album.nfo").is_file()
        assert (alb2_dir / "folder.jpg").is_file()

        a_nfo = read_artist_nfo(artist_dir / "artist.nfo")
        assert a_nfo.metadata.name == "Daft Punk"
        assert a_nfo.metadata.musicbrainz_artist_id == "056e4f3e-d505-4dad-8ec1-d04f521cbb56"

        alb1_nfo = read_album_nfo(alb1_dir / "album.nfo")
        assert alb1_nfo.metadata.musicbrainz_album_id == "rel-discovery-14"
        assert alb1_nfo.metadata.label == "Virgin"

        alb2_nfo = read_album_nfo(alb2_dir / "album.nfo")
        assert alb2_nfo.metadata.musicbrainz_album_id == "rel-homework-1"
        assert alb2_nfo.metadata.label == "Soma"

        # 4. Verify Music UI renders Artist -> Album -> Track tree
        r_ui = client.get("/music")
        assert r_ui.status_code == 200
        assert "Daft Punk" in r_ui.text
        assert "Discovery" in r_ui.text
        assert "Homework" in r_ui.text
