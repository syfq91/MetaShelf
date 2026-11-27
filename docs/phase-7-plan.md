# Phase 7 Implementation Plan: Batch, Polish and Automation

## Tasks

1. **Multi-select batch actions with dry-run and diff preview**
   - Service: `src/metashelf/services/batch.py` (`preview_batch_diff`, `execute_batch_action` supporting `save`, `auto_match`, `fetch_subtitles` with `dry_run: bool`).
   - UI & Routes: multi-select checkboxes, sticky batch bar (`Auto-match`, `Save all`, `Dry-run` toggle) in `src/metashelf/web/templates/movies/index.html`, `_list.html`, `_batch_preview.html`, and `POST /movies/batch` in `src/metashelf/web/routers/movies.py`.
   - Tests (first): `tests/test_batch.py`.

2. **Scheduled rescans and optional filesystem watching**
   - Config: `watch_enabled: bool = False` in `src/metashelf/config.py`.
   - Scheduler & Watcher: `src/metashelf/jobs/scheduler.py` (`LibraryScheduler` parsing simple interval/cron strings and `LibraryWatcher` using `watchfiles.awatch` when enabled).
   - Wired into `lifespan` in `src/metashelf/main.py`.
   - Tests (first): `tests/test_scheduler.py`.

3. **Per-library settings: sidecar naming scheme, language, artwork limits**
   - Service: `src/metashelf/services/library_prefs.py` (`LibraryPreferences`, `get_library_prefs`, `set_library_prefs`).
   - UI & Routes: per-library prefs modal/panel in `src/metashelf/web/routers/settings.py` and `src/metashelf/web/templates/settings/_library_prefs.html`.
   - Tests (first): `tests/test_library_prefs.py`.

4. **Export and import of settings, DB rebuild command (`metashelf rebuild-index`)**
   - CLI: `src/metashelf/cli.py` + `[project.scripts]` in `pyproject.toml` (`metashelf rebuild-index`).
   - Export/Import: `GET /settings/export` and `POST /settings/import` in `src/metashelf/web/routers/settings.py`.
   - Tests (first): `tests/test_cli_and_export.py`.

5. **Accessibility pass, keyboard shortcuts (arrow keys in list, Ctrl+S to save), empty states, error toasts**
   - Templates: `src/metashelf/web/templates/base.html` (keyboard shortcuts `ArrowUp`/`ArrowDown`/`Ctrl+S`, HTMX error toast handler, ARIA attributes), `movies/index.html`.
   - Tests: `tests/test_accessibility_and_shortcuts.py`.
