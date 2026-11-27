# Phase 0 & Phase 1 Implementation Plan

## Phase 0: Skeleton

### Tasks
1. **Repo, tooling & config (`pyproject.toml`, ruff, mypy, pytest, pre-commit, `.env.example`, `.gitignore`)**
   - Files: `pyproject.toml`, `.gitignore`, `.env.example`, `.pre-commit-config.yaml`, `README.md`, `docs/adr/0001-architecture-and-stack.md`
   - Tests: `tests/test_smoke.py` (import check)
2. **FastAPI app factory, config loading, `/healthz`**
   - Files: `src/metashelf/__init__.py`, `src/metashelf/config.py`, `src/metashelf/main.py`
   - Tests: `tests/test_health.py` (`/healthz` returns 200, config defaults & env overrides)
3. **SQLAlchemy models and first Alembic migration**
   - Files: `src/metashelf/db/__init__.py`, `src/metashelf/db/models.py`, `src/metashelf/db/session.py`, `alembic.ini`, `src/metashelf/db/migrations/env.py`, `src/metashelf/db/migrations/script.py.mako`, `src/metashelf/db/migrations/versions/0001_initial.py`, `src/metashelf/domain/__init__.py`, `src/metashelf/domain/models.py`
   - Tests: `tests/test_db.py` (WAL mode, migration up/down, CRUD on core tables)
4. **Tailwind + DaisyUI build in Docker, base layout template with sidebar, top bar and theme toggle**
   - Files: `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, `src/metashelf/web/__init__.py`, `src/metashelf/web/static/input.css`, `src/metashelf/web/static/htmx.min.js` (or vendored/static), `src/metashelf/web/templates/base.html`, `src/metashelf/web/templates/index.html`, `src/metashelf/web/routers/__init__.py`, `src/metashelf/web/routers/pages.py`
   - Tests: `tests/test_ui_shell.py` (base layout renders sidebar, top bar, theme toggle)
5. **Auth (setup, login, logout, CSRF)**
   - Files: `src/metashelf/auth/__init__.py`, `src/metashelf/auth/security.py`, `src/metashelf/auth/deps.py`, `src/metashelf/web/routers/auth.py`, `src/metashelf/web/templates/auth/setup.html`, `src/metashelf/web/templates/auth/login.html`
   - Tests: `tests/test_auth.py` (first-run setup, login, logout, invalid password rate limit, CSRF protection on POST, protected route redirect)
6. **GitHub Actions CI (lint, type-check, tests, docker build)**
   - Files: `.github/workflows/ci.yml`
   - Tests: Full `ruff`, `mypy`, `pytest`, and `docker build` verification.

*Phase 0 Done when:* `docker compose up` shows a login page (or setup on first run), then an empty app shell with the MediaElch-style layout.

---

## Phase 1: Core engine plus Movies (vertical slice)

### Tasks
1. **Library CRUD in Settings, directory picker restricted to mounted roots**
   - Files: `src/metashelf/web/routers/settings.py`, `src/metashelf/web/templates/settings/index.html`, `src/metashelf/web/templates/settings/_libraries.html`, `src/metashelf/web/templates/settings/_dir_picker.html`, `src/metashelf/services/paths.py`
   - Tests: `tests/test_settings_libraries.py` (create/delete/toggle library, path traversal rejection outside allowed roots, dir picker stays inside roots)
2. **Movie scanner and `guessit` parsing, adopt existing NFOs through the reader**
   - Files: `src/metashelf/scanner/__init__.py`, `src/metashelf/scanner/movie.py`, `src/metashelf/scanner/parser.py`
   - Tests (write first): `tests/test_movie_parser.py` (table of real-world filenames), `tests/test_movie_scanner.py` (folder & flat movies, incremental mtime/size, adopting existing NFO)
3. **Provider base classes, rate limiter, cache, TMDB provider (search, fetch, artwork)**
   - Docs first: `docs/providers.md` (TMDB v3 API docs & terms), `docs/open-questions.md`
   - Files: `src/metashelf/providers/__init__.py`, `src/metashelf/providers/base.py`, `src/metashelf/providers/rate_limit.py`, `src/metashelf/providers/cache.py`, `src/metashelf/providers/tmdb.py`, `tests/fixtures/tmdb/*.json`
   - Tests (write first): `tests/test_rate_limiter.py`, `tests/test_tmdb_provider.py` (respx mocked from recorded fixtures, missing key error, cache hit)
4. **Kodi movie NFO writer and reader with round-trip golden tests, artwork downloader with validation**
   - Docs first: `docs/kodi-nfo-movie.md` (official Kodi NFO movie XML schema)
   - Files: `src/metashelf/writers/__init__.py`, `src/metashelf/writers/atomic.py`, `src/metashelf/writers/kodi_nfo_movie.py`, `src/metashelf/writers/artwork.py`, `src/metashelf/readers/__init__.py`, `src/metashelf/readers/kodi_nfo_movie.py`, `tests/fixtures/nfo/*.nfo`
   - Tests (write first): `tests/test_kodi_nfo_movie.py` (golden round-trip, unknown XML element preservation, atomic write + `.bak` creation), `tests/test_artwork_writer.py` (content-type, size limit, Pillow validation, SSRF/URL check)
5. **Library view: list pane, detail pane, Info and Artwork tabs, Save and Revert**
   - Files: `src/metashelf/web/routers/movies.py`, `src/metashelf/web/templates/movies/index.html`, `src/metashelf/web/templates/movies/_list.html`, `src/metashelf/web/templates/movies/_detail.html`, `src/metashelf/web/templates/movies/_tab_info.html`, `src/metashelf/web/templates/movies/_tab_artwork.html`, `src/metashelf/web/templates/movies/_tab_files.html`
   - Tests: `tests/test_movies_ui.py` (list filtering/sorting, detail view, edit -> dirty state, save -> writes NFO, revert -> restores from disk/DB)
6. **Scrape modal with field checklist**
   - Files: `src/metashelf/web/templates/movies/_scrape_modal.html`, endpoints in `src/metashelf/web/routers/movies.py`
   - Tests: `tests/test_scrape_modal.py` (search prefilled from guessit, select candidate, selective field checklist apply)
7. **Job queue, worker, SSE progress, Jobs page**
   - Files: `src/metashelf/jobs/__init__.py`, `src/metashelf/jobs/queue.py`, `src/metashelf/jobs/worker.py`, `src/metashelf/jobs/handlers.py`, `src/metashelf/web/routers/jobs.py`, `src/metashelf/web/templates/jobs/index.html`, `src/metashelf/web/templates/jobs/_table.html`
   - Tests: `tests/test_jobs.py` (persisted queue, scan_library job, cancellation, idempotency, SSE progress stream)
8. **Auto-match for movies with confidence threshold**
   - Files: `src/metashelf/matching/__init__.py`, `src/metashelf/matching/movie.py`, `docs/adr/0002-auto-match-scoring.md`
   - Tests (write first): `tests/test_movie_matcher.py` (high confidence auto-accept, ambiguous margin leaves unmatched, manual match preserved across rescan), `tests/test_phase1_e2e.py` (20-movie test library: scan -> auto-match with TMDB fixtures -> edit in UI -> save -> verify NFO & artwork match golden expectations).

*Phase 1 Done when:* a test library of 20 movie folders can be scanned, auto-matched against recorded TMDB fixtures, edited in the UI, and saved, producing NFO and artwork that match golden files.
