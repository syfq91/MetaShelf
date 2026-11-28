"""Settings and library CRUD routes."""

import html
import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.auth.deps import CurrentUser, DbSession, require_csrf
from metashelf.db.models import Library, Setting
from metashelf.domain.models import LibraryType
from metashelf.services.library_prefs import (
    LibraryPreferences,
    get_library_prefs,
    set_library_prefs,
)
from metashelf.services.paths import (
    PathTraversalError,
    list_directories,
)
from metashelf.services.settings_backup import export_settings_bundle, import_settings_bundle
from metashelf.web.templating import get_nav_context, render_template

router = APIRouter(prefix="/settings", tags=["settings"])

SETTING_TMDB_KEY = "tmdb_api_key"
SETTING_LANGUAGE = "metadata_language"
SETTING_MOVIE_NAMING = "movie_naming_scheme"


async def get_setting_value(session: AsyncSession, key: str, default: str = "") -> str:
    row = await session.get(Setting, key)
    if row is None:
        return default
    val = json.loads(row.value_json)
    return str(val) if val is not None else default


async def set_setting_value(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    encoded = json.dumps(value)
    if row is None:
        session.add(Setting(key=key, value_json=encoded))
    else:
        row.value_json = encoded


async def _libraries_context(session: AsyncSession) -> dict[str, object]:
    libraries = (
        await session.execute(select(Library).order_by(Library.id.asc()))
    ).scalars().all()
    return {"libraries": libraries}


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
) -> HTMLResponse:
    """Render the settings page."""
    nav_ctx = await get_nav_context(session)
    lib_ctx = await _libraries_context(session)
    settings = request.app.state.settings
    tmdb_key = await get_setting_value(session, SETTING_TMDB_KEY, settings.tmdb_api_key)
    language = await get_setting_value(session, SETTING_LANGUAGE, "en-US")
    naming = await get_setting_value(session, SETTING_MOVIE_NAMING, "file")
    return render_template(
        request,
        "settings/index.html",
        {
            "active_nav": "settings",
            "library_types": [t.value for t in LibraryType],
            "tmdb_api_key_set": bool(tmdb_key),
            "language": language,
            "movie_naming": naming,
            **nav_ctx,
            **lib_ctx,
        },
    )


@router.get("/dir-picker", response_class=HTMLResponse)
async def dir_picker(
    request: Request,
    _user: CurrentUser,
    path: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Return an HTMX directory picker fragment for browsing folders."""
    error: str | None = None
    current: str | None = None
    parent: str | None = None
    dirs: list[dict[str, str]] = []
    try:
        current, parent, dirs = list_directories(path)
    except PathTraversalError as exc:
        error = str(exc)
    return render_template(
        request,
        "settings/_dir_picker.html",
        {
            "current_path": current,
            "parent_path": parent,
            "dirs": dirs,
            "error": error,
        },
    )


@router.post(
    "/libraries",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def create_library(
    request: Request,
    session: DbSession,
    name: Annotated[str, Form()],
    lib_type: Annotated[str, Form()],
    root_path: Annotated[str, Form()],
    scan_cron: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Create a new media library at the selected directory."""
    clean_name = name.strip()
    clean_root = root_path.strip()
    error: str | None = None

    if not clean_name:
        error = "Library name is required."
    elif lib_type not in {t.value for t in LibraryType}:
        error = f"Unsupported library type: {lib_type}"
    elif not clean_root:
        error = "Library folder path is required."
    else:
        resolved = Path(clean_root).resolve()
        if not resolved.exists() or not resolved.is_dir():
            error = f"Directory does not exist: {resolved}"
        else:
            existing = (
                await session.execute(
                    select(Library).where(Library.root_path == str(resolved))
                )
            ).scalar_one_or_none()
            if existing is not None:
                error = f"A library already exists for {resolved}."
            else:
                session.add(
                    Library(
                        name=clean_name,
                        type=lib_type,
                        root_path=str(resolved),
                        enabled=True,
                        scan_cron=scan_cron.strip() or None,
                    )
                )
                await session.commit()

    lib_ctx = await _libraries_context(session)
    status_code = status.HTTP_400_BAD_REQUEST if error else status.HTTP_200_OK
    return render_template(
        request,
        "settings/_libraries.html",
        {"error": error, **lib_ctx},
        status_code=status_code,
    )


@router.post(
    "/libraries/{library_id}/toggle",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def toggle_library(
    request: Request,
    session: DbSession,
    library_id: int,
) -> HTMLResponse:
    """Toggle a library's enabled status."""
    lib = await session.get(Library, library_id)
    if lib is not None:
        lib.enabled = not lib.enabled
        await session.commit()
    lib_ctx = await _libraries_context(session)
    return render_template(request, "settings/_libraries.html", lib_ctx)


@router.delete(
    "/libraries/{library_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def delete_library(
    request: Request,
    session: DbSession,
    library_id: int,
) -> HTMLResponse:
    """Delete a library from the index (files on disk are untouched)."""
    lib = await session.get(Library, library_id)
    if lib is not None:
        await session.delete(lib)
        await session.commit()
    lib_ctx = await _libraries_context(session)
    return render_template(request, "settings/_libraries.html", lib_ctx)


@router.get("/libraries/{library_id}/prefs", response_class=HTMLResponse)
async def get_library_prefs_form(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    library_id: int,
) -> HTMLResponse:
    """Render per-library preferences form."""
    lib = await session.get(Library, library_id)
    if lib is None:
        return HTMLResponse("Library not found", status_code=status.HTTP_404_NOT_FOUND)
    prefs = await get_library_prefs(session, library_id)
    return render_template(
        request,
        "settings/_library_prefs.html",
        {"library": lib, "prefs": prefs, "saved": False},
    )


@router.post(
    "/libraries/{library_id}/prefs",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def save_library_prefs_form(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    library_id: int,
    naming_scheme: Annotated[str, Form()] = "file",
    language: Annotated[str, Form()] = "en-US",
    max_posters: Annotated[int, Form(ge=1, le=50)] = 3,
    max_fanart: Annotated[int, Form(ge=1, le=50)] = 3,
) -> HTMLResponse:
    """Save per-library preferences."""
    lib = await session.get(Library, library_id)
    if lib is None:
        return HTMLResponse("Library not found", status_code=status.HTTP_404_NOT_FOUND)
    scheme: Literal["file", "movie_nfo"] = (
        "movie_nfo" if naming_scheme == "movie_nfo" else "file"
    )
    prefs = LibraryPreferences(
        naming_scheme=scheme,
        language=language.strip() or "en-US",
        max_posters=max_posters,
        max_fanart=max_fanart,
    )
    await set_library_prefs(session, library_id, prefs)
    return render_template(
        request,
        "settings/_library_prefs.html",
        {"library": lib, "prefs": prefs, "saved": True},
    )


@router.post(
    "/preferences",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def save_preferences(
    request: Request,
    session: DbSession,
    tmdb_api_key: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "en-US",
    movie_naming: Annotated[str, Form()] = "file",
) -> HTMLResponse:
    """Save provider and metadata preferences."""
    if tmdb_api_key.strip():
        await set_setting_value(session, SETTING_TMDB_KEY, tmdb_api_key.strip())
    await set_setting_value(session, SETTING_LANGUAGE, language.strip() or "en-US")
    if movie_naming in {"file", "folder"}:
        await set_setting_value(session, SETTING_MOVIE_NAMING, movie_naming)
    await session.commit()
    return HTMLResponse('<div class="alert alert-success text-sm py-2">Preferences saved.</div>')


@router.get("/export")
async def export_settings(
    _user: CurrentUser,
    session: DbSession,
) -> JSONResponse:
    """Export settings and library definitions as JSON."""
    bundle = await export_settings_bundle(session)
    return JSONResponse(
        content=bundle,
        headers={"Content-Disposition": 'attachment; filename="metashelf-settings.json"'},
    )


@router.post(
    "/import",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def import_settings(
    request: Request,
    _user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile | None, File()] = None,
    payload: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Import settings and library definitions from JSON upload or form payload."""
    raw_text = payload.strip()
    if file is not None and file.filename:
        raw_bytes = await file.read()
        raw_text = raw_bytes.decode("utf-8", errors="replace").strip()
    if not raw_text:
        return HTMLResponse(
            '<div class="alert alert-error text-sm py-2">No JSON payload provided.</div>',
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        bundle = json.loads(raw_text)
        libs_count, settings_count = await import_settings_bundle(session, bundle)
    except (json.JSONDecodeError, ValueError, KeyError, PathTraversalError) as exc:
        return HTMLResponse(
            f'<div class="alert alert-error text-sm py-2">{html.escape(str(exc))}</div>',
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return HTMLResponse(
        f'<div class="alert alert-success text-sm py-2">'
        f"Imported {libs_count} library(ies) and {settings_count} setting(s)."
        f"</div>"
    )
