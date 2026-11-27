"""Tests for scheduled library rescans and optional filesystem watcher."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from metashelf.config import Settings
from metashelf.db.models import Job, Library
from metashelf.jobs.scheduler import LibraryScheduler, parse_cron_interval_seconds
from metashelf.main import create_app


def test_parse_cron_interval_seconds() -> None:
    assert parse_cron_interval_seconds("") is None
    assert parse_cron_interval_seconds("invalid") is None
    assert parse_cron_interval_seconds("*/15 * * * *") == 900
    assert parse_cron_interval_seconds("0 */6 * * *") == 21600
    assert parse_cron_interval_seconds("0 3 * * *") == 86400
    assert parse_cron_interval_seconds("@hourly") == 3600
    assert parse_cron_interval_seconds("@daily") == 86400


async def test_scheduler_tick_enqueues_due_libraries_without_duplicates(tmp_path: Path) -> None:
    root1 = tmp_path / "movies1"
    root2 = tmp_path / "movies2"
    root3 = tmp_path / "movies3"
    root1.mkdir()
    root2.mkdir()
    root3.mkdir()
    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(tmp_path))
    app = create_app(settings=app_settings)

    with TestClient(app):
        async with app.state.session_factory() as session:
            lib_due = Library(
                name="Due",
                type="movie",
                root_path=str(root1),
                enabled=True,
                scan_cron="*/5 * * * *",
            )
            lib_disabled = Library(
                name="Disabled",
                type="movie",
                root_path=str(root2),
                enabled=False,
                scan_cron="*/5 * * * *",
            )
            lib_no_cron = Library(
                name="Manual",
                type="movie",
                root_path=str(root3),
                enabled=True,
                scan_cron=None,
            )
            session.add_all([lib_due, lib_disabled, lib_no_cron])
            await session.commit()
            due_id = lib_due.id

        scheduler = LibraryScheduler(app.state.session_factory)
        now = datetime.now(UTC)

        # First tick enqueues due library
        enqueued_1 = await scheduler.tick(now=now)
        assert enqueued_1 == [due_id]

        # Second immediate tick does NOT duplicate pending job
        enqueued_2 = await scheduler.tick(now=now + timedelta(minutes=10))
        assert enqueued_2 == []

        # Mark job done in the past -> next tick after interval enqueues again
        async with app.state.session_factory() as session:
            jobs = list((await session.scalars(select(Job))).all())
            assert len(jobs) == 1
            jobs[0].status = "done"
            jobs[0].created_at = now - timedelta(minutes=10)
            jobs[0].finished_at = now - timedelta(minutes=10)
            await session.commit()

        enqueued_3 = await scheduler.tick(now=now)
        assert enqueued_3 == [due_id]
