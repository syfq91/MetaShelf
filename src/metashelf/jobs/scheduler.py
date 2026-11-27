"""Background scheduler for cron-based rescans and optional filesystem watching."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from watchfiles import awatch

from metashelf.db.models import Job, Library
from metashelf.jobs.queue import enqueue_job

logger = logging.getLogger(__name__)


def parse_cron_interval_seconds(cron_expr: str) -> int | None:
    """Parse common 5-field cron expressions or @hourly/@daily into an interval in seconds."""
    expr = cron_expr.strip()
    if not expr:
        return None
    if expr == "@hourly":
        return 3600
    if expr == "@daily":
        return 86400

    parts = expr.split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if dom != "*" or month != "*" or dow != "*":
        return None

    if minute.startswith("*/") and hour == "*":
        step = minute[2:]
        if step.isdigit() and int(step) > 0:
            return int(step) * 60
        return None

    if minute.isdigit() and hour.startswith("*/"):
        step = hour[2:]
        if step.isdigit() and int(step) > 0:
            return int(step) * 3600
        return None

    if minute.isdigit() and hour == "*":
        return 3600

    if minute.isdigit() and hour.isdigit():
        return 86400

    return None


async def _has_active_scan_job(session: AsyncSession, library_id: int) -> bool:
    active_jobs = list(
        (
            await session.scalars(
                select(Job).where(
                    Job.type == "scan_library",
                    Job.status.in_(["pending", "running"]),
                )
            )
        ).all()
    )
    for job in active_jobs:
        try:
            payload = json.loads(job.payload_json)
            if payload.get("library_id") == library_id:
                return True
        except Exception:
            continue
    return False


async def _last_scan_time(session: AsyncSession, library_id: int) -> datetime | None:
    jobs = list(
        (
            await session.scalars(
                select(Job)
                .where(Job.type == "scan_library")
                .order_by(Job.id.desc())
                .limit(50)
            )
        ).all()
    )
    for job in jobs:
        try:
            payload = json.loads(job.payload_json)
            if payload.get("library_id") == library_id:
                dt = job.finished_at or job.created_at
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=UTC)
                return dt
        except Exception:
            continue
    return None


class LibraryScheduler:
    """Periodically checks libraries with `scan_cron` and enqueues `scan_library` jobs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        poll_interval: float = 60.0,
    ) -> None:
        self._session_factory = session_factory
        self._poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def tick(self, now: datetime | None = None) -> list[int]:
        """Check all enabled libraries with a cron schedule and enqueue due scans."""
        current = now or datetime.now(UTC)
        enqueued_ids: list[int] = []
        async with self._session_factory() as session:
            libraries = list(
                (
                    await session.scalars(
                        select(Library).where(Library.enabled.is_(True))
                    )
                ).all()
            )
            for lib in libraries:
                interval = parse_cron_interval_seconds(lib.scan_cron or "")
                if interval is None:
                    continue
                if await _has_active_scan_job(session, lib.id):
                    continue
                last_run = await _last_scan_time(session, lib.id)
                if last_run is None or (current - last_run).total_seconds() >= interval:
                    await enqueue_job(session, "scan_library", {"library_id": lib.id})
                    enqueued_ids.append(lib.id)
        return enqueued_ids

    async def start(self) -> None:
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("Scheduler tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)


class LibraryWatcher:
    """Optional filesystem watcher that enqueues library scans on disk changes."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        debounce_ms: int = 2000,
    ) -> None:
        self._session_factory = session_factory
        self._debounce_ms = debounce_ms
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        async with self._session_factory() as session:
            libraries = list(
                (await session.scalars(select(Library).where(Library.enabled.is_(True)))).all()
            )
        roots = [
            (lib.id, Path(lib.root_path).resolve())
            for lib in libraries
            if Path(lib.root_path).exists()
        ]
        if not roots:
            return
        watch_paths = [str(path) for _, path in roots]
        try:
            async for changes in awatch(
                *watch_paths,
                stop_event=self._stop_event,
                debounce=self._debounce_ms,
            ):
                changed_paths = [Path(p).resolve() for _, p in changes]
                async with self._session_factory() as session:
                    for lib_id, root_path in roots:
                        if any(
                            cp == root_path or root_path in cp.parents for cp in changed_paths
                        ) and not await _has_active_scan_job(session, lib_id):
                            await enqueue_job(session, "scan_library", {"library_id": lib_id})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Filesystem watcher failed")
