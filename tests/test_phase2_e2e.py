"""Phase 2 E2E test: multi-season show matched once -> all episode NFOs and thumbs generated."""

import asyncio
from io import BytesIO
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from metashelf.config import Settings
from metashelf.db.models import Item, Job, Library
from metashelf.jobs.queue import enqueue_job
from metashelf.main import create_app
from metashelf.readers.kodi_nfo_tv import read_episode_nfo, read_tvshow_nfo

FIXTURES = Path(__file__).parent / "fixtures" / "tmdb"


def _setup_and_login(_client: TestClient) -> str:
    return ""


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (160, 90), color=(40, 80, 120)).save(buf, format="JPEG")
    return buf.getvalue()


@respx.mock
async def test_phase2_show_match_generates_all_episode_nfos_and_thumbs(tmp_path: Path) -> None:
    tv_root = tmp_path / "tv"
    show_dir = tv_root / "Breaking Bad (2008)"
    s1_dir = show_dir / "Season 01"
    s2_dir = show_dir / "Season 02"
    s1_dir.mkdir(parents=True)
    s2_dir.mkdir(parents=True)

    (s1_dir / "Breaking.Bad.S01E01.mkv").write_bytes(b"s1e1")
    (s1_dir / "Breaking.Bad.S01E02.mkv").write_bytes(b"s1e2")
    (s2_dir / "Breaking.Bad.S02E01.mkv").write_bytes(b"s2e1")

    s2_json = """{
      "id": 3573,
      "season_number": 2,
      "name": "Season 2",
      "episodes": [
        {
          "id": 62090,
          "season_number": 2,
          "episode_number": 1,
          "name": "Seven Thirty-Seven",
          "overview": "Walt and Jesse face Tuco.",
          "air_date": "2009-03-08",
          "runtime": 47,
          "still_path": "/s2e1.jpg",
          "vote_average": 8.6,
          "vote_count": 300,
          "crew": [],
          "guest_stars": []
        }
      ]
    }"""

    respx.get("https://api.themoviedb.org/3/search/tv").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "search_tv_breaking_bad.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/tv/1396").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "tv_1396.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/tv/1396/images").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "tv_1396_images.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/tv/1396/season/1").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "tv_1396_s1.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/tv/1396/season/1/images").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "tv_1396_s1_images.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://api.themoviedb.org/3/tv/1396/season/2").mock(
        return_value=httpx.Response(200, text=s2_json)
    )
    respx.get("https://api.themoviedb.org/3/tv/1396/season/2/images").mock(
        return_value=httpx.Response(200, json={"id": 3573, "posters": []})
    )
    respx.get(url__startswith="https://image.tmdb.org/t/p/original/").mock(
        return_value=httpx.Response(
            200, content=_jpeg_bytes(), headers={"content-type": "image/jpeg"}
        )
    )

    app_settings = Settings(
        config_dir=tmp_path / "config",
        media_roots=str(tv_root),
        tmdb_api_key="dummy-key",
    )
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        # 1. Create TV library and scan
        r_lib = client.post(
            "/settings/libraries",
            headers=headers,
            data={"name": "TV", "lib_type": "tv", "root_path": str(tv_root)},
        )
        assert r_lib.status_code == 200

        async with app.state.session_factory() as session:
            lib = (await session.execute(select(Library))).scalar_one()
            await enqueue_job(session, "scan_library", {"library_id": lib.id})
        await app.state.job_worker.run_one_pending()

        async with app.state.session_factory() as session:
            show = (
                await session.execute(select(Item).where(Item.kind == "show"))
            ).scalar_one()
            show_id = show.id

        # 2. Match once at show level via scrape/apply
        r_apply = client.post(
            f"/tv/{show_id}/scrape/apply",
            headers=headers,
            data={"provider_id": "1396"},
        )
        assert r_apply.status_code == 200

        # 3. Wait for the queued fetch_show_episodes job to finish
        for _ in range(50):
            async with app.state.session_factory() as session:
                jobs = (await session.execute(select(Job).order_by(Job.id.desc()))).scalars().all()
                if jobs and jobs[0].status in {"completed", "failed"}:
                    assert jobs[0].error is None, f"Job failed: {jobs[0].error}"
                    assert jobs[0].status == "completed"
                    break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("fetch_show_episodes job did not finish in time")

        # 4. Verify tvshow.nfo, show poster/fanart, season01-poster, and all episode NFOs & thumbs
        assert (show_dir / "tvshow.nfo").is_file()
        assert (show_dir / "poster.jpg").is_file()
        assert (show_dir / "fanart.jpg").is_file()
        assert (show_dir / "season01-poster.jpg").is_file()

        tv_nfo = read_tvshow_nfo(show_dir / "tvshow.nfo")
        assert tv_nfo.metadata.title == "Breaking Bad"
        assert tv_nfo.metadata.tvdb_id == "81189"

        for ep_file, expected_title in [
            (s1_dir / "Breaking.Bad.S01E01", "Pilot"),
            (s1_dir / "Breaking.Bad.S01E02", "Cat's in the Bag..."),
            (s2_dir / "Breaking.Bad.S02E01", "Seven Thirty-Seven"),
        ]:
            nfo_p = ep_file.parent / f"{ep_file.name}.nfo"
            thumb_p = ep_file.parent / f"{ep_file.name}-thumb.jpg"
            assert nfo_p.is_file(), f"Missing {nfo_p}"
            assert thumb_p.is_file(), f"Missing {thumb_p}"
            ep_nfo = read_episode_nfo(nfo_p)
            assert ep_nfo.episodes[0].title == expected_title
