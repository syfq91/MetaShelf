# Phase 8 Implementation Plan: Hardening and Release

## Scope (from `docs/PLAN.md`)
1. Security review: path traversal tests, SSRF and image validation tests, rate limits.
2. Performance test on a 50k-item synthetic library (list queries must be paginated and indexed).
3. Structured logging, log level setting, metrics endpoint.
4. README, versioned Docker image publishing workflow, changelog.

## Existing Interfaces Reused
- `resolve_within_roots`, `resolve_within_root` (`src/metashelf/services/paths.py`)
- `validate_artwork_url`, `download_artwork` (`src/metashelf/writers/artwork.py`)
- `LoginRateLimiter` (`src/metashelf/auth/security.py`)
- `Settings` (`src/metashelf/config.py`), `create_app` (`src/metashelf/main.py`)
- `_build_movie_query` (`src/metashelf/web/routers/movies.py`)
- No existing provider, writer, or reader interfaces are changed.

## Tasks

### Task 1: Security hardening & tests (`path traversal`, `SSRF`, `image validation`, `rate limits`)
- **Files to change:**
  - `src/metashelf/writers/artwork.py` (reject `ip.is_unspecified` and `ip.is_multicast` in `validate_artwork_url`)
- **Tests to add:**
  - `tests/test_security.py`: path traversal (`../`, symlink escape, `/settings/libraries`, `/settings/browse`), SSRF (`localhost`, `127.0.0.1`, `0.0.0.0`, `169.254.169.254`, `10.0.0.1`, `[::1]`, `file://`, redirect to private IP), image validation (invalid content-type, >20 MiB size limit, corrupt image bytes, valid PNG), and login rate-limit `429`.

### Task 2: 50k-item synthetic library performance test
- **Tests to add:**
  - `tests/test_performance_50k.py`: bulk-insert 50,000 `Item` rows, verify paginated `_build_movie_query` and `/movies/list` return 50 items per page quickly (<1s) and `Item` indexes exist.

### Task 3: Structured logging, log level setting, and `/metrics` endpoint
- **Files to create/change:**
  - `src/metashelf/logging_config.py` (`JsonFormatter`, `configure_logging`)
  - `src/metashelf/config.py` (add `log_format: str = "json"`)
  - `src/metashelf/main.py` (configure logging on startup, add `GET /metrics` Prometheus text endpoint)
- **Tests to add:**
  - `tests/test_logging_and_metrics.py`: JSON log formatting at configured `log_level`, `GET /metrics` returning `metashelf_items_total`, `metashelf_libraries_total`, `metashelf_jobs_total`.

### Task 4: README, changelog, and versioned Docker image publishing workflow
- **Files to create/change:**
  - `README.md` (comprehensive documentation: features, Docker quick start, env vars, CLI, dev commands)
  - `CHANGELOG.md` (`0.1.0` release notes)
  - `.github/workflows/release.yml` (tag-triggered `v*` multi-stage Docker build & push to GHCR)
