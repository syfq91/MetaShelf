"""Jobs page, actions, and SSE progress stream."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select

from metashelf.auth.deps import CurrentUser, DbSession, require_csrf
from metashelf.db.models import Job
from metashelf.jobs.queue import JobWorker, enqueue_job
from metashelf.web.templating import get_nav_context, render_template

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
) -> HTMLResponse:
    """Render the Jobs page."""
    nav_ctx = await get_nav_context(session)
    jobs = (
        await session.execute(select(Job).order_by(Job.id.desc()).limit(100))
    ).scalars().all()
    return render_template(
        request,
        "jobs/index.html",
        {"active_nav": "jobs", "jobs": jobs, **nav_ctx},
    )


@router.get("/table", response_class=HTMLResponse)
async def jobs_table_fragment(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
) -> HTMLResponse:
    """Return HTMX fragment for the jobs table."""
    jobs = (
        await session.execute(select(Job).order_by(Job.id.desc()).limit(100))
    ).scalars().all()
    return render_template(request, "jobs/_table.html", {"jobs": jobs})


@router.post(
    "/scan/{library_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def start_scan_job(
    request: Request,
    session: DbSession,
    library_id: int,
) -> HTMLResponse:
    """Enqueue a scan_library job."""
    job = await enqueue_job(session, "scan_library", {"library_id": library_id})
    worker: JobWorker = request.app.state.job_worker
    worker.notify_new_job()
    return HTMLResponse(
        f'<div class="alert alert-info text-xs py-1">Queued scan job #{job.id}.</div>'
    )


@router.post(
    "/auto-match/{library_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def start_auto_match_job(
    request: Request,
    session: DbSession,
    library_id: int,
) -> HTMLResponse:
    """Enqueue an auto_match job."""
    job = await enqueue_job(session, "auto_match", {"library_id": library_id})
    worker: JobWorker = request.app.state.job_worker
    worker.notify_new_job()
    return HTMLResponse(
        f'<div class="alert alert-info text-xs py-1">Queued auto-match job #{job.id}.</div>'
    )


@router.post(
    "/fetch-subtitles/{library_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def start_fetch_subtitles_job(
    request: Request,
    session: DbSession,
    library_id: int,
) -> HTMLResponse:
    """Enqueue a fetch_subtitles job for a movie or TV library."""
    job = await enqueue_job(
        session,
        "fetch_subtitles",
        {"library_id": library_id, "languages": ["en"], "only_missing": True},
    )
    worker: JobWorker = request.app.state.job_worker
    worker.notify_new_job()
    return HTMLResponse(
        f'<div class="alert alert-info text-xs py-1">Queued subtitles job #{job.id}.</div>'
    )


@router.post(
    "/fetch-lyrics/{library_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def start_fetch_lyrics_job(
    request: Request,
    session: DbSession,
    library_id: int,
) -> HTMLResponse:
    """Enqueue a fetch_lyrics job for a music library."""
    job = await enqueue_job(
        session,
        "fetch_lyrics",
        {"library_id": library_id, "only_missing": True},
    )
    worker: JobWorker = request.app.state.job_worker
    worker.notify_new_job()
    return HTMLResponse(
        f'<div class="alert alert-info text-xs py-1">Queued lyrics job #{job.id}.</div>'
    )


@router.post(
    "/{job_id}/cancel",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def cancel_job(
    request: Request,
    session: DbSession,
    job_id: int,
) -> HTMLResponse:
    """Cancel a pending or running job."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    worker: JobWorker = request.app.state.job_worker
    worker.request_cancel(job_id)
    if job.status == "pending":
        job.status = "cancelled"
        job.finished_at = datetime.now(UTC)
        await session.commit()

    jobs = (
        await session.execute(select(Job).order_by(Job.id.desc()).limit(100))
    ).scalars().all()
    return render_template(request, "jobs/_table.html", {"jobs": jobs})


@router.get("/stream")
async def jobs_stream(
    request: Request,
    _user: CurrentUser,
) -> StreamingResponse:
    """Server-Sent Events stream notifying clients when jobs change."""
    worker: JobWorker = request.app.state.job_worker
    session_factory = request.app.state.session_factory

    async def event_generator() -> AsyncIterator[str]:
        while True:
            if await request.is_disconnected():
                break
            async with session_factory() as session:
                jobs = (
                    await session.execute(select(Job).order_by(Job.id.desc()).limit(20))
                ).scalars().all()
                payload = [
                    {
                        "id": j.id,
                        "type": j.type,
                        "status": j.status,
                        "progress": j.progress,
                        "total": j.total,
                    }
                    for j in jobs
                ]
            yield f"event: jobs\ndata: {json.dumps(payload)}\n\n"
            await worker.wait_for_update(timeout=3.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
