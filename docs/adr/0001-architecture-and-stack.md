# ADR 0001: Architecture and Stack

## Status
Accepted

## Context
MetaShelf is a self-hosted, headless metadata manager with a MediaElch-style two-pane UI that runs in Docker and treats the filesystem as the source of truth.

## Decision
- **Python 3.12 + FastAPI + Jinja2 + HTMX 2 + Tailwind CSS / DaisyUI 5**: Server-rendered HTML fragments avoid SPA build complexity while keeping the two-pane interactive experience responsive.
- **SQLite (WAL mode) + SQLAlchemy 2.0 + Alembic**: Zero-config embedded database acting as a rebuildable index and provider cache.
- **Atomic writes with `.bak` backups**: Sidecar files are written to a temp file in the same directory and renamed, preserving one-generation `.bak` backups. Media files are never modified.
- **Offline-first CI**: Provider HTTP calls use `httpx` and are replayed via `respx` from recorded fixtures.
