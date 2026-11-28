"""Jinja2 template rendering helpers."""

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf import __version__
from metashelf.db.models import Item, Job

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def get_nav_context(session: AsyncSession) -> dict[str, Any]:
    """Fetch sidebar item counts and active job count."""
    rows = (
        await session.execute(select(Item.kind, func.count(Item.id)).group_by(Item.kind))
    ).all()
    nav_counts = {kind: count for kind, count in rows}
    active_jobs = (
        await session.execute(
            select(func.count(Job.id)).where(Job.status.in_(["pending", "running"]))
        )
    ).scalar_one()
    return {
        "nav_counts": nav_counts,
        "active_jobs_count": active_jobs,
    }


def render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render a Jinja2 template with common MetaShelf context."""
    settings = request.app.state.settings
    merged: dict[str, Any] = {
        "base_url": settings.base_url.rstrip("/"),
        "app_version": __version__,
        "nav_counts": {},
        "active_jobs_count": 0,
        "active_nav": "",
    }
    if context:
        merged.update(context)
    return templates.TemplateResponse(request, template_name, merged, status_code=status_code)
