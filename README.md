# MetaShelf

Self-hosted metadata manager for **movies**, **TV shows**, **music**, **ebooks (EPUB)**, and **comics (CBZ)**. Runs headless in Docker on Linux and saves sidecar metadata, artwork, subtitles, and lyrics next to your media files.

## Features

- **Filesystem as source of truth:** Never modifies media files (MKV/MP4/MP3/FLAC/EPUB/CBZ); writes standard sidecars (`*.nfo`, `*.opf`, `ComicInfo.xml`, `*.srt`, `*.lrc`) and artwork (`poster.jpg`, `fanart.jpg`, `cover.jpg`, `folder.jpg`) atomically with `.bak` backups.
- **5 Media Types:**
  - **Movies & TV Shows:** Kodi-compatible NFO reader/writer (preserving unknown XML tags), TMDB, TheTVDB, and fanart.tv providers.
  - **Music:** Artist/Album/Track NFOs, MusicBrainz + Cover Art Archive, and LRCLIB synced/plain lyrics (`.lrc`).
  - **Ebooks:** EPUB OPF/DC metadata + Open Library & Google Books providers.
  - **Comics:** `ComicInfo.xml` sidecars + Comic Vine provider.
  - **Subtitles:** OpenSubtitles REST API v1 with movie file hashing and `.srt` sidecars.
- **Web UI:** FastAPI + HTMX + Tailwind/DaisyUI two-pane library views, manual scrape modal, multi-select batch actions with dry-run diff preview, per-library settings, and settings export/import.
- **Automation & CLI:** Cron-based scheduled rescans, optional filesystem watcher (`METASHELF_WATCH_ENABLED=true`), and `metashelf rebuild-index` CLI.
- **Security & Observability:** Designed for local LAN or reverse-proxy deployments (no built-in login), library path traversal confinement, SSRF & Pillow artwork validation, structured JSON logging, `/healthz`, and `/metrics`.

## Quick Start (Docker)

```bash
# Edit environment variables in docker-compose.yml (especially METASHELF_SECRET_KEY)
docker compose up -d
```

Then open `http://localhost:8000`. Place MetaShelf behind a reverse proxy (e.g., Caddy, Traefik, or Authelia) if exposing it beyond your local LAN.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `METASHELF_SECRET_KEY` | *(auto-generated)* | Session & CSRF signing secret (auto-generated in `/config/.secret_key` on first run if omitted) |
| `METASHELF_CONFIG_DIR` | `/config` | SQLite database and thumbnails directory |
| `METASHELF_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `METASHELF_LOG_FORMAT` | `json` | `json` or `text` |
| `METASHELF_WATCH_ENABLED` | `false` | Enable `watchfiles` filesystem watcher |
| `METASHELF_TMDB_API_KEY` | `""` | Optional default TMDB v3 API key |

## CLI

Rebuild the SQLite index from sidecars on disk:

```bash
metashelf rebuild-index --config-dir /config
```

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src
uv run pytest -m "not live"
```
