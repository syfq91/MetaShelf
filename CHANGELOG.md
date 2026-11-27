# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-11-27

### Added
- **Phase 0–1 (Core & Movies):** FastAPI + SQLite (WAL) + Alembic, session auth with CSRF & rate limiting, path confinement, atomic sidecar writes with `.bak`, movie scanner/parser, Kodi movie NFO reader/writer, TMDB provider, artwork downloader with SSRF/Pillow validation, background job queue, and two-pane Movies UI.
- **Phase 2 (TV Shows):** TV show/season/episode scanner & parser, Kodi TV NFO readers/writers, TheTVDB v4, TMDB TV, and fanart.tv providers, and TV Shows UI.
- **Phase 3 (Music):** Artist/album/track scanner, Kodi music NFO readers/writers, MusicBrainz + Cover Art Archive providers, and Music UI.
- **Phase 4 (Ebooks & Comics):** EPUB OPF/DC and `ComicInfo.xml` readers/writers, ebook/comic scanners & parsers, Open Library, Google Books, and Comic Vine providers, and Ebooks/Comics UI.
- **Phase 5 (Subtitles & Lyrics):** OpenSubtitles v1 provider with file hashing, `.srt` subtitle writer, LRCLIB `.lrc` lyrics provider/writer, and UI integration.
- **Phase 6 (Multi-item & Polish):** Search/filter/sort polish across libraries.
- **Phase 7 (Batch & Automation):** Multi-select batch actions with dry-run diff preview, cron rescan scheduler & optional `watchfiles` watcher, per-library preferences, settings export/import, `metashelf rebuild-index` CLI, ARIA landmarks, keyboard shortcuts, and HTMX error toasts.
- **Phase 8 (Hardening & Release):** Security test suite (path traversal, SSRF, image validation, rate limits), 50k-item synthetic pagination/index benchmark, structured JSON logging, `/metrics` Prometheus endpoint, README, and GHCR Docker release workflow.
