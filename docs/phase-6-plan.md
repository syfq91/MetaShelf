# Phase 6 Implementation Plan: Subtitles and Lyrics

## Tasks

1. **Subtitle provider interface and OpenSubtitles provider**
   - Protocols & models: `SubtitleQuery`, `SubtitleCandidate`, `SubtitleDownload`, `SubtitleProvider`, `QuotaExceededError` in `src/metashelf/providers/base.py`.
   - Config: `opensubtitles_api_key`, `opensubtitles_username`, `opensubtitles_password` in `src/metashelf/config.py`.
   - Movie hash: `compute_opensubtitles_hash` in `src/metashelf/providers/opensubtitles.py`.
   - Provider: `OpenSubtitlesProvider` (file-hash search first, then TMDB/IMDb ID + season/episode, then title/year; login + `/download` with rate limiting, caching, and quota error handling).
   - Tests (first): `tests/test_opensubtitles_provider.py` + `tests/fixtures/opensubtitles/*.json`.

2. **Subtitle writer and Subtitles tab in Movies & TV detail panes**
   - Writer: `src/metashelf/writers/subtitles.py` (`subtitle_target_path`, `normalize_subtitle_to_utf8`, `write_subtitle_file` with no-overwrite-by-default & `.bak` on forced overwrite).
   - Router endpoints & UI: `Subtitles` tab in `movies/_detail.html` and `tv/_detail.html` (episode) + `POST /movies/{id}/subtitles/search`, `download`, `delete` (and `/tv/{id}/subtitles/...`).
   - Tests (first): `tests/test_subtitle_writer.py`.

3. **Lyrics provider interface, LRCLIB provider, `.lrc`/`.txt` writers, and Lyrics tab**
   - Protocols & models: `LyricsQuery`, `LyricsCandidate`, `LyricsProvider` in `src/metashelf/providers/base.py`.
   - Provider: `LRCLIBProvider` in `src/metashelf/providers/lrclib.py` (`GET /api/get` then `/api/search`, synced preference + plain fallback).
   - Writer: `src/metashelf/writers/lyrics.py` (`write_lyrics_file` writing `<track>.lrc` or `<track>.txt` in UTF-8 with no-overwrite-by-default & `.bak` on forced overwrite).
   - UI: `Lyrics` tab for tracks in `music/_detail.html` + `src/metashelf/web/routers/music.py` endpoints.
   - Tests (first): `tests/test_lrclib_provider.py`, `tests/test_lyrics_writer.py` + `tests/fixtures/lrclib/*.json`.

4. **Jobs `fetch_subtitles` and `fetch_lyrics` with per-library languages and only-missing mode**
   - Service & handlers: `fetch_subtitles_for_library` and `fetch_lyrics_for_library` in `src/metashelf/jobs/handlers.py` (registered in `main.py`).
   - Tests: `tests/test_phase6_e2e.py` (movies and episodes get `.srt` for configured languages; music tracks get `.lrc` or `.txt`; existing files are never overwritten in only-missing mode).
