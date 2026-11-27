"""Top-level HTML page routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from metashelf.auth.deps import CurrentUser, DbSession
from metashelf.web.templating import get_nav_context, render_template

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, _user: CurrentUser, session: DbSession) -> HTMLResponse:
    """Render the home shell."""
    nav_ctx = await get_nav_context(session)
    return render_template(request, "index.html", {"active_nav": "home", **nav_ctx})
