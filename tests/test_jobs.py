"""Tests for persisted job queue, worker execution, cancellation, and Jobs UI."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from metashelf.config import Settings
from metashelf.db.models import Item, Job, Library
from metashelf.jobs.queue import enqueue_job
from metashelf.main import create_app


def _setup_and_login(_client: TestClient) -> str:
    return ""


async def test_scan_job_execution_and_cancellation(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    m_dir = media_root / "Inception (2010)"
    m_dir.mkdir(parents=True)
    (m_dir / "Inception (2010).mkv").write_bytes(b"video")

    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        async with app.state.session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.commit()
            lib_id = lib.id

        # Enqueue and run scan_library deterministically
        async with app.state.session_factory() as session:
            job = await enqueue_job(session, "scan_library", {"library_id": lib_id})
            job_id = job.id

        did_work = await app.state.job_worker.run_one_pending()
        assert did_work is True

        async with app.state.session_factory() as session:
            done_job = await session.get(Job, job_id)
            assert done_job is not None
            assert done_job.status == "completed"
            items = (await session.execute(select(Item))).scalars().all()
            assert len(items) == 1
            assert items[0].title == "Inception"

        # Test Jobs page and cancellation of a pending job
        async with app.state.session_factory() as session:
            j2 = await enqueue_job(session, "scan_library", {"library_id": lib_id})
            j2_id = j2.id

        r_cancel = client.post(f"/jobs/{j2_id}/cancel", headers=headers)
        assert r_cancel.status_code == 200
        assert "cancelled" in r_cancel.text

        r_page = client.get("/jobs")
        assert r_page.status_code == 200
        assert "scan_library" in r_page.text
