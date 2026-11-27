"""Persisted SQLite job queue and in-process asyncio worker pool."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from metashelf.config import Settings
from metashelf.db.models import Job

logger = logging.getLogger(__name__)

JobHandler = Callable[
    [AsyncSession, Job, dict[str, Any], httpx.AsyncClient, Settings],
    Awaitable[None],
]


async def enqueue_job(
    session: AsyncSession,
    job_type: str,
    payload: dict[str, Any] | None = None,
) -> Job:
    """Persist a new pending job in SQLite."""
    job = Job(
        type=job_type,
        payload_json=json.dumps(payload or {}),
        status="pending",
        progress=0,
        total=0,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


class JobWorker:
    """In-process asyncio worker pool consuming persisted SQLite jobs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        http_client: httpx.AsyncClient,
        settings: Settings,
        handlers: dict[str, JobHandler],
        concurrency: int = 2,
    ) -> None:
        self._session_factory = session_factory
        self._http_client = http_client
        self._settings = settings
        self._handlers = handlers
        self._concurrency = concurrency
        self._stop_event = asyncio.Event()
        self._wakeup_event = asyncio.Event()
        self._update_condition = asyncio.Condition()
        self._cancelled_ids: set[int] = set()
        self._tasks: list[asyncio.Task[None]] = []

    def notify_new_job(self) -> None:
        """Wake up idle workers when a new job is enqueued."""
        self._wakeup_event.set()

    async def _broadcast_update(self) -> None:
        async with self._update_condition:
            self._update_condition.notify_all()

    async def wait_for_update(self, timeout: float = 5.0) -> None:
        async with self._update_condition:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._update_condition.wait(), timeout=timeout)

    def request_cancel(self, job_id: int) -> None:
        self._cancelled_ids.add(job_id)

    def is_cancelled(self, job_id: int) -> bool:
        return job_id in self._cancelled_ids

    async def start(self) -> None:
        """Recover any interrupted running jobs and start worker tasks."""
        async with self._session_factory() as session:
            await session.execute(
                update(Job).where(Job.status == "running").values(status="pending")
            )
            await session.commit()

        self._stop_event.clear()
        self._tasks = [
            asyncio.create_task(self._worker_loop(idx))
            for idx in range(self._concurrency)
        ]

    async def stop(self) -> None:
        """Signal workers to stop and await their completion."""
        self._stop_event.set()
        self._wakeup_event.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def run_one_pending(self) -> bool:
        """Claim and execute a single pending job (useful for deterministic tests)."""
        async with self._session_factory() as session:
            job = (
                await session.execute(
                    select(Job)
                    .where(Job.status == "pending")
                    .order_by(Job.created_at.asc(), Job.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if job is None:
                return False

            if self.is_cancelled(job.id):
                job.status = "cancelled"
                job.finished_at = datetime.now(UTC)
                await session.commit()
                await self._broadcast_update()
                return True

            job.status = "running"
            await session.commit()
            await self._broadcast_update()

            handler = self._handlers.get(job.type)
            if handler is None:
                job.status = "failed"
                job.error = f"Unknown job type: {job.type}"
                job.finished_at = datetime.now(UTC)
                await session.commit()
                await self._broadcast_update()
                return True

            try:
                payload: dict[str, Any] = json.loads(job.payload_json or "{}")
                await handler(session, job, payload, self._http_client, self._settings)
                if self.is_cancelled(job.id) or job.status == "cancelled":
                    job.status = "cancelled"
                else:
                    job.status = "completed"
            except Exception as exc:
                logger.exception("Job %s (%s) failed", job.id, job.type)
                job.status = "failed"
                job.error = str(exc)
            finally:
                job.finished_at = datetime.now(UTC)
                await session.commit()
                await self._broadcast_update()
            return True

    async def _worker_loop(self, _worker_id: int) -> None:
        while not self._stop_event.is_set():
            did_work = await self.run_one_pending()
            if not did_work:
                self._wakeup_event.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wakeup_event.wait(), timeout=2.0)
