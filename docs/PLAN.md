# MetaShelf: Build Plan for an AI Coding Agent

Working name. A self-hosted metadata manager for movies, TV shows, music, ebooks and comics. It runs headless in Docker on a Linux server, is used from a web browser, downloads metadata, artwork, subtitles and lyrics from online providers, and saves them next to the media files. The UI is modeled on MediaElch (library list on the left, detail editor on the right, scrape dialog).

## 1. Scope

**In scope for v1**

- Five media types: movies, TV shows (show, season, episode), music (artist, album, track), ebooks (EPUB), comics (CBZ).
- Subtitles for movies and TV episodes, and lyrics for music tracks, downloaded from online providers and saved next to the media.
- Library scanning, filename parsing, matching to online providers, manual search and pick, editing fields, saving sidecar files and artwork.
- Batch operations (auto-match and save a whole library or a filtered selection), with progress.
- Single-admin web UI, Docker image and compose file.

**Non-goals for v1**

- Playback, transcoding, downloading media, renaming or moving media files, multi-user roles, native mobile apps.
- Writing tags inside audio, EPUB or CBZ files (planned as an optional later phase).
- Generating subtitles or lyrics with speech recognition.

## 2. Principles (the agent must follow these)

1. **The filesystem is the source of truth.** The database is a rebuildable index and cache. Deleting the DB and rescanning must restore the full state from sidecar files.
2. **Never destroy user data.** Never modify media files. Write sidecars atomically (temp file in the same directory, then rename). Keep a one-generation backup (`.bak`) before overwriting an existing sidecar. Provide a dry-run mode for batch jobs.
3. **Plugins behind interfaces.** Providers (where metadata comes from) and writers (what format is saved) are separate, swappable modules.
4. **Server-rendered HTML.** Jinja2 templates returning full pages or HTML fragments. HTMX for interactivity. Vanilla JS only where HTMX cannot do the job. No SPA framework.
5. **Testable offline.** CI must pass with no network access. Provider calls are replayed from recorded fixtures.
6. **Security by default.** All paths are resolved and must stay inside configured library roots. Image downloads only from URLs returned by providers, with size and content-type limits.

## 3. Tech stack

| Concern | Choice |
| --- | --- |
| Language | Python 3.12 |
| Web framework | FastAPI with Jinja2 templates (use `jinja2-fragments` or separate partial templates for HTMX responses) |
| Frontend | HTMX 2 (+ SSE extension for job progress), Tailwind CSS + DaisyUI 5 |
| CSS build | Tailwind standalone CLI in a Docker build stage; generated CSS is not committed |
| DB | SQLite (WAL mode) via SQLAlchemy 2.0 + Alembic migrations |
| HTTP client | httpx (async), with retry, timeout and per-provider rate limiter |
| Filename parsing | `guessit` for movies and TV |
| Audio tags (read) | `mutagen` |
| Ebook and comic parsing (read) | stdlib `zipfile` + `lxml` for EPUB/OPF`  and CBZ/ComicInfo.xml ` |
| XML | `lxml` |
| Images | Pillow (validate, optionally resize thumbnails for the UI cache) |
| Settings and models | pydantic v2, pydantic-settings |
| Jobs | In-process asyncio worker pool, queue persisted in SQLite |
| Tooling | uv or pip-tools, ruff, mypy (strict on core modules), pytest, pytest-asyncio, respx (HTTP mocking) |

## 4. Repository layout

```
metashelf/
  pyproject.toml
  Dockerfile
  docker-compose.yml
  docs/                  # this plan, ADRs, provider notes
  src/metashelf/
    main.py              # FastAPI app factory
    config.py            # env + config file settings
    db/                  # models.py, session.py, migrations/
    domain/              # pydantic models: Movie, Show, Season, Episode, Artist, Album, Track, Ebook, Comic
    scanner/             # walkers + filename parsers per media type
    providers/           # base.py, tmdb.py, tvdb.py, fanart.py, musicbrainz.py, coverart.py, openlibrary.py, googlebooks.py, comicvine.py, opensubtitles.py, lrclib.py
    writers/             # kodi_nfo_movie.py, kodi_nfo_tv.py, kodi_nfo_music.py, opf_ebook.py, comicinfo_xml.py, subtitles.py, lyrics.py, artwork.py
    readers/             # parse existing sidecars back into domain models
    matching/            # scoring and candidate ranking
    jobs/                # queue, worker, job types, SSE progress
    web/                 # routers/, templates/, static/
    auth/                # session login, CSRF
  tests/
    fixtures/            # tiny fake libraries, recorded provider responses
```

## 5. Domain and database

Each media item has a **path identity** (folder or file path relative to its library root) and a **metadata state**.

Tables (names are suggestions):

- `library(id, name, type, root_path, enabled, scan_cron)`
- `item(id, library_id, kind, parent_id, rel_path, title, year, state, provider_ids_json, metadata_json, sidecar_mtime, scanned_at)` where `kind` is one of movie, show, season, episode, artist, album, track, ebook, comic.
- `sidecar_file(id, item_id, kind, rel_path, lang, format, synced, source, source_id, sha256, created_at)` where `kind` is subtitle or lyrics, so downloaded files are tracked separately from artwork.
- `artwork(id, item_id, type, rel_path, source_url, width, height)` with type in poster, fanart, banner, thumb, cover, logo.
- `job(id, type, payload_json, status, progress, total, error, created_at, finished_at)`
- `provider_cache(key, response_json, fetched_at, ttl)`
- `setting(key, value_json)`

`state` values: `unmatched` (no sidecar), `matched` (provider IDs known), `complete` (sidecar and required artwork written), `dirty` (edited in UI, not yet saved), `error`.

The canonical stored form of metadata is the normalized pydantic model serialized as JSON, plus the provider IDs. Sidecar files are generated from it. Readers parse existing sidecars on scan so that files created by Kodi or MediaElch are adopted, not overwritten blindly.

## 6. Provider interface

Each provider implements a small async protocol. The agent must read each provider's current official API docs and terms (rate limits, attribution, key requirements) before implementing it, and record findings in `docs/providers.md`. Do not guess field names.

```python
class Provider(Protocol):
    id: str                       # 'tmdb'
    media_kinds: set[str]         # {'movie', 'show'}
    needs_api_key: bool
    async def search(self, kind: str, query: SearchQuery) -> list[Candidate]: ...
    async def fetch(self, kind: str, provider_id: str, lang: str) -> NormalizedMetadata: ...
    async def artwork(self, kind: str, provider_id: str) -> list[ArtworkCandidate]: ...
```

Planned providers:

- **Movies and TV:** TMDB (primary), TheTVDB v4 (optional), fanart.tv (extra artwork).
- **Music:** MusicBrainz (no key, strict 1 request per second, descriptive User-Agent required), Cover Art Archive for covers, fanart.tv or TheAudioDB for artist images (optional).
- **Ebooks:** Open Library (no key), Google Books (optional key), Hardcover (optional, later).
- **Comics:** Comic Vine (primary, the source ComicTagger uses; needs a free API key and has rate limits). Evaluate other sources later.
- **Subtitles:** OpenSubtitles (needs an account and API key; download quotas apply). Match by file hash first. Evaluate other sources later.
- **Lyrics:** LRCLIB (no key; offers synced and plain lyrics). Evaluate other sources later, and read their terms first because lyrics licensing is restrictive.

Subtitle and lyrics providers use their own small protocols with the same rate limiting, caching and key handling: `SubtitleProvider.search(video_query)` returns `SubtitleCandidate` items and `.download(candidate)` returns the file bytes; `LyricsProvider.search(track_query)` returns `LyricsCandidate` items. Candidates carry language, format, a synced flag, and a match score.

Cross-cutting provider requirements: per-provider rate limiter, response cache in `provider_cache`, language preference setting, clear error when an API key is missing, and a provider test button in Settings.

## 7. Sidecar formats (written next to the media)

| Kind | Files |
| --- | --- |
| Movie | `<movie filename>.nfo` (Kodi movie NFO), `<movie filename>-poster.jpg`, `<movie filename>-fanart.jpg`; if the movie lives in its own folder, also support `movie.nfo`, `poster.jpg`, `fanart.jpg` (configurable naming scheme) |
| TV show | `tvshow.nfo`, `poster.jpg`, `fanart.jpg`, `banner.jpg` in the show folder; `seasonNN-poster.jpg`; per episode `<episode filename>.nfo` and `<episode filename>-thumb.jpg` |
| Music | `artist.nfo`, `folder.jpg`, `fanart.jpg` in the artist folder; `album.nfo` and `folder.jpg` (or `cover.jpg`) in the album folder |
| Ebook (EPUB) | `<ebook filename>.opf` (OPF metadata) and `<ebook filename>.jpg` (cover), saved next to the `.epub` file |
| Comic (CBZ) | `<comic filename>.xml` (ComicInfo.xml schema, saved as a sidecar) and `<comic filename>.jpg` (cover), saved next to the `.cbz` file |
| Subtitles (movies and episodes) | `<video filename>.<lang>.srt`, for example `Movie (2020).en.srt`; a flag such as `forced` goes in as an extra dot part. The agent must check the current Kodi and Jellyfin external-subtitle naming docs before fixing the scheme |
| Lyrics (music tracks) | `<track filename>.lrc` for time-synced lyrics and `<track filename>.txt` for plain lyrics, next to the audio file |

The agent must check the current Kodi NFO documentation and sample NFOs from a real Kodi or MediaElch library and write them into `tests/fixtures/` as golden files. Round-trip tests are required: read a golden NFO, write it, and compare (ignoring whitespace).

Unknown XML elements in an existing NFO must be preserved when re-saving (do not drop fields the app does not understand).

For comics, use the ComicInfo.xml schema; the agent must check the current published schema for field names and allowed values. ComicInfo.xml is normally stored inside the archive, so saving it as `<comic filename>.xml` beside the file is a deliberate choice: the reader must also accept a ComicInfo.xml embedded in the CBZ, and the sidecar wins when both exist. The CBZ itself is never modified. The same rule applies to OPF: preserve elements the app does not understand.

## 8. UI specification (MediaElch-like)

Overall layout, built with DaisyUI components, dark and light theme toggle, desktop first, usable on tablet:

1. **Top bar:** app name, global search box, job activity indicator (opens a jobs drawer), theme toggle, logout.
2. **Left sidebar (menu):** Movies, TV Shows, Music, Ebooks, Comics, Jobs, Settings. Each media section shows a count badge.
3. **Library view, two panes:**
   - *Left pane, item list:* filterable and sortable table or list with columns for title, year, and status icons (has metadata, has poster, has fanart). Filter chips: All, Unmatched, Missing artwork, Dirty. Multi-select checkboxes. Virtual or paginated loading via `hx-trigger=revealed` infinite scroll.
   - *Right pane, detail editor:* poster and fanart preview at top, then tabs (DaisyUI `tabs`): **Info** (editable fields, genres and cast as tag inputs), **Artwork** (grid of current and candidate images, click to choose), **Files** (file paths, sidecars present, parse results), a Subtitles tab for movies and episodes (existing files, search online, preview, download, delete) and a Lyrics tab for tracks (plain or synced text, search online, preview, save), and for TV/music a tree to switch between show, season, episode or artist, album, track.
   - Action bar: **Search online** (opens scrape modal), **Save**, **Revert**, **Reload from disk**.
4. **Scrape modal:** provider dropdown, query and year inputs prefilled from the filename parse, results list with poster, title, year, and overview, then a field checklist (choose which fields and artwork to apply), then Apply.
5. **Batch bar** (appears when items are selected): Auto-match, Fetch missing artwork, Fetch subtitles, Fetch lyrics, Save all, with a dry-run checkbox. Starts a job and shows progress.
6. **Jobs page:** table of jobs with live progress (SSE) and error details.
7. **Settings:** libraries (add path, type, rescan schedule), providers and API keys, language, naming scheme for sidecars, artwork preferences (which types, max count), subtitle preferences (ordered languages, include forced or hearing-impaired, overwrite rules), lyrics preferences (synced first, plain fallback), account password.

HTMX conventions: every interactive control returns an HTML fragment; use `hx-target` and `hx-swap` with out-of-band swaps for status badges and toasts; forms validated server-side and re-rendered with DaisyUI error styles. No client-side state store.

## 9. Background jobs

Job types: `scan_library`, `scan_item`, `auto_match`, `fetch_metadata`, `download_artwork`, `write_sidecars`, `batch_save`, fetch\_subtitles, fetch\_lyrics. Requirements:

- Persisted queue (survive restarts), configurable concurrency, cancellation, per-job progress and error capture.
- Progress streamed to the browser with SSE.
- Idempotent: re-running a job must not duplicate data.
- Library scans are incremental (compare mtime and size) and run on a schedule and on demand. Optionally use `watchfiles` to react to changes (note that inotify is unreliable on network mounts, so keep scheduled scans as the fallback).

## 10. Auto-matching

1. Parse filename and folder names (`guessit` for video, tags and folder structure for music, embedded OPF or filename for ebooks, ComicInfo.xml or filename for comics).
2. Query the provider, then score each candidate by title similarity, year, runtime, ISBN or track count where available.
3. Auto-accept only above a configurable confidence threshold and when the margin over the second candidate is large enough. Otherwise leave `unmatched` and surface the top candidates in the UI.
4. Store the match decision and provider IDs so that re-scans do not redo or override manual choices.

**Subtitles and lyrics matching.** Subtitles: search by file hash first, then by provider or IMDb/TMDB ID plus season and episode, then by title and year; prefer the configured languages in order and skip a language that already has a file. Lyrics: search by artist, title, album and duration, prefer synced lyrics, fall back to plain text. Both are only fetched when missing unless the person forces a refresh.

## 11. Docker and deployment

- Multi-stage Dockerfile: Tailwind and DaisyUI build stage, then a slim Python runtime stage running as a non-root user.
- Support `PUID` and `PGID` environment variables so written sidecars have the same ownership as the media.
- Volumes: `/config` (SQLite DB, cache, thumbnails, logs) and one or more media mounts (read-write, because sidecars are written there).
- Environment: `METASHELF_SECRET_KEY`, `TZ`, optional API keys (can also be set in the UI), `METASHELF_BASE_URL` for reverse proxies.
- `/healthz` endpoint and Docker `HEALTHCHECK`.
- Compose example with one library mount per media type, and a note on running behind a reverse proxy (Caddy or Traefik) for TLS.
- Auth: first-run setup creates the admin account; Argon2 password hashing; session cookies (HttpOnly, SameSite=Lax); CSRF token sent with every HTMX request via `hx-headers`; login rate limiting.

## 12. Implementation phases

Each phase ends with passing tests, a working Docker image, and an updated `docs/` page. The agent should commit after each numbered task.

### Phase 0: Skeleton

1. Create the repo, `pyproject.toml`, ruff, mypy, pytest, pre-commit.
2. FastAPI app factory, config loading, `/healthz`.
3. SQLAlchemy models and the first Alembic migration.
4. Tailwind + DaisyUI build in Docker, base layout template with sidebar, top bar and theme toggle.
5. Auth (setup, login, logout, CSRF).
6. GitHub Actions CI (lint, type-check, tests, docker build).

*Done when:* `docker compose up` shows a login page, then an empty app shell with the MediaElch-style layout.

### Phase 1: Core engine plus Movies (vertical slice)

1. Library CRUD in Settings, directory picker restricted to mounted roots.
2. Movie scanner and `guessit` parsing, adopt existing NFOs through the reader.
3. Provider base classes, rate limiter, cache, TMDB provider (search, fetch, artwork).
4. Kodi movie NFO writer and reader with round-trip golden tests, artwork downloader with validation.
5. Library view: list pane, detail pane, Info and Artwork tabs, Save and Revert.
6. Scrape modal with field checklist.
7. Job queue, worker, SSE progress, Jobs page.
8. Auto-match for movies with confidence threshold.

*Done when:* a test library of 20 movie folders can be scanned, auto-matched against recorded TMDB fixtures, edited in the UI, and saved, producing NFO and artwork that match golden files.

### Phase 2: TV shows

1. Show, season and episode scanner (handle `Show/Season 01/S01E02` and common variants, multi-episode files, specials).
2. TMDB TV provider (and TheTVDB as an optional second provider), fanart.tv provider.
3. `tvshow.nfo`, episode NFO and season artwork writers and readers.
4. Tree navigation in the detail pane; batch fetch for all episodes of a show.

*Done when:* a show with several seasons can be matched once at show level and all episode NFOs and thumbs are generated.

### Phase 3: Music

1. Artist, album and track scanner using folder structure plus `mutagen` tags.
2. MusicBrainz provider (strict rate limiting, User-Agent) and Cover Art Archive.
3. `artist.nfo`, `album.nfo`, `folder.jpg` writers and readers.
4. Album match using track count and track titles to disambiguate releases.

*Done when:* an artist folder with two albums gets correct NFOs and covers using recorded fixtures.

### Phase 4: Ebooks (EPUB)

1. Ebook scanner for `.epub` files; read the OPF embedded inside each EPUB to prefill fields.
2. Open Library and Google Books providers; ISBN-first matching.
3. Writer and reader for `<ebook filename>.opf` and the cover `<ebook filename>.jpg`; adopt existing sidecars.
4. Series, author and multiple-author fields.

*Done when:* a folder of EPUBs gets a `.opf` and a `.jpg` beside each file, and rebuilding the index from an empty DB restores identical metadata.

### Phase 5: Comics (CBZ)

1. Comic scanner for `.cbz` files: series folders, issue number, volume and year parsed from filenames; read an embedded ComicInfo.xml from inside the CBZ when present.
2. Comic Vine provider (volume search, then issue fetch); read its current terms, key requirements and rate limits first.
3. Writer and reader for `<comic filename>.xml` (ComicInfo.xml schema) with golden-file tests; cover saved as `<comic filename>.jpg`, taken from the provider or the archive's first page (configurable).
4. UI: series grouping in the list (series, then issue); fields for series, number, volume, year, publisher, writers, artists and summary.

*Done when:* a folder of CBZ files in series folders is matched against recorded Comic Vine fixtures and each file gets a `.xml` and a `.jpg` beside it, with the archives left untouched.

### Phase 6: Subtitles and lyrics

1. Subtitle provider interface and the OpenSubtitles provider (file-hash search first, then ID plus season and episode, then title and year); respect rate limits and the daily download quota.
2. Subtitle writer: save as `<video filename>.<lang>.srt`, convert to UTF-8, never overwrite an existing file without a backup; Subtitles tab in the detail pane for movies and episodes.
3. Lyrics provider interface and the LRCLIB provider (match on artist, title, album and duration); writers for `<track filename>.lrc` and `.txt`; Lyrics tab for tracks.
4. Jobs `fetch_subtitles` and `fetch_lyrics` with per-library language settings and an only-missing mode.

*Done when:* movies and episodes in a test library get `.srt` files for the configured languages and tracks get `.lrc` or `.txt` files, using recorded fixtures, with no existing file overwritten.

### Phase 7: Batch, polish and automation

1. Multi-select batch actions with dry-run and a diff preview of what would change.
2. Scheduled rescans and optional filesystem watching.
3. Per-library settings: sidecar naming scheme, language, artwork limits.
4. Export and import of settings, DB rebuild command (`metashelf rebuild-index`).
5. Accessibility pass, keyboard shortcuts (arrow keys in list, Ctrl+S to save), empty states, error toasts.

### Phase 8: Hardening and release

1. Security review: path traversal tests, SSRF and image validation tests, rate limits.
2. Performance test on a 50k-item synthetic library (list queries must be paginated and indexed).
3. Structured logging, log level setting, metrics endpoint (optional).
4. README, screenshots, versioned Docker image publishing, changelog.

### Later (backlog)

- Embedding tags into audio files, EPUBs and CBZ archives (ComicInfo.xml inside the archive), cover-image matching for comics, rename and organize files, subtitle timing adjustment, extra providers (Hardcover, TheAudioDB), concert and music video support, multi-user, plugin loading from a directory.

## 13. Testing strategy

- **Unit tests:** filename parsers (large table of real-world names), scoring, writers and readers.
- **Golden-file tests:** every sidecar writer against checked-in expected files; round-trip read, write, read.
- **Provider tests:** respx-mocked responses recorded from real APIs once and committed (strip keys). A separate manual `pytest -m live` suite hits real APIs and is never run in CI.
- **Integration tests:** build a temporary fake library on disk, run scan, match and save through the FastAPI test client, then assert on files.
- **UI tests:** Playwright smoke tests for login, list, edit, scrape, and save flows.
- **Safety tests:** path traversal attempts, read-only media mount, interrupted write (no partial files), concurrent saves of the same item.

## 14. Working rules for the AI agent

1. Work phase by phase; do not start a phase until the previous one meets its done criteria.
2. Before implementing a provider or file format, read the official documentation and write short notes in `docs/`. Do not rely on memory for API fields or XML schemas. If something cannot be verified, add it to `docs/open-questions.md` and choose the safest default.
3. Write the test first for parsers, writers and matchers.
4. Keep modules small and typed. Core modules must pass `mypy --strict`.
5. Never commit API keys. Use environment variables and a `.env.example`.
6. Record important decisions as short ADRs in `docs/adr/`.
7. After each task: run lint, type-check and tests, then commit with a clear message.
8. Never write outside configured library roots or `/config`.
9. Prefer boring, well-known libraries over clever code. Avoid adding a dependency without a note explaining why.
10. When requirements are ambiguous, implement the simplest behavior that is reversible and note the assumption.

## 15. Risks and open questions

- **Provider terms and keys:** TMDB, TheTVDB, fanart.tv, Comic Vine and Google Books need keys, and each has usage terms (attribution, rate limits). Decide how users obtain and enter keys, and show required attribution in the UI.
- **Subtitle and lyrics rights:** both are copyrighted and providers set their own terms and download quotas (OpenSubtitles limits downloads per account). Cache results, keep files local next to the media, never redistribute them, and surface quota errors clearly in the Jobs page.
- **Network filesystems:** SMB and NFS mounts make mtime, inotify and permissions unreliable. Rely on scheduled scans and explicit rescans, and test with a read-only and a slow mount.
- **Interoperability:** Kodi, Jellyfin, Plex-style agents and Audiobookshelf each read slightly different sidecar conventions. Start with Kodi NFO, OPF for ebooks and ComicInfo.xml for comics, and make naming schemes configurable: per-file sidecar names such as \`\<filename>.opf\` and \`\<filename>.xml\` are not read by every tool.
- **Matching quality for music, ebooks and comics:** many releases and editions per work. Keep manual correction fast and never let auto-match overwrite a manual choice.
- **Scope creep:** music, ebooks and comics each add a full new surface area. Ship movies end to end first, and keep the provider and writer interfaces strict so later media types are additive.
