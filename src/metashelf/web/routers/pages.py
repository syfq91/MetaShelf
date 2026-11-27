"""Top-level HTML page routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from metashelf.web.templating import render_template

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the home shell."""
    return render_template(request, "index.html", {"active_nav": "home"})
