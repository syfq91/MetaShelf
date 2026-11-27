# Phase 2 Implementation Plan: TV Shows

## Tasks

1. **Show, season and episode scanner (`Show/Season 01/S01E02`, variants, multi-episode files, specials)**
   - Domain models: `ShowMetadata`, `SeasonMetadata`, `EpisodeMetadata`, `NormalizedMetadata` in `src/metashelf/domain/models.py` (+ ADR `docs/adr/0003-normalized-metadata-union.md`).
   - Scanner: `parse_tv_episode_filename` in `src/metashelf/scanner/parser.py` (using `guessit` with `type="episode"`), `scan_tv_library` in `src/metashelf/scanner/tv.py` (creates/updates hierarchical `show` -> `season` -> `episode` `Item` rows via `parent_id`, handles `Season 01`, `Specials`/`Season 00`/`S00E01`, multi-episode lists `[1, 2]`, and adopts existing `tvshow.nfo`, `seasonNN-poster.jpg`, and `<episode>.nfo`).
   - Tests (first): `tests/test_tv_parser.py`, `tests/test_tv_scanner.py`.

2. **TMDB TV provider, TheTVDB v4 provider (optional), and fanart.tv provider**
   - Update `Provider.fetch` return type to `NormalizedMetadata` in `src/metashelf/providers/base.py`.
   - Extend `TMDBProvider` in `src/metashelf/providers/tmdb.py` with `media_kinds = {"movie", "show", "episode"}`, `search("show", ...)`, `fetch("show", ...)`, `artwork("show", ...)`, plus `fetch_season_episodes(...)` and `season_artwork(...)`.
   - Add `TheTVDBProvider` in `src/metashelf/providers/tvdb.py` (JWT login, search, series fetch, episodes, artwork) and `FanartTVProvider` in `src/metashelf/providers/fanart.py` (TV artwork via `tvdb_id`).
   - Add `tmdb_api_key` / `tvdb_api_key` / `fanart_api_key` settings in `config.py` and `settings.py` (with provider test button in Settings).
   - Tests (first): `tests/test_tmdb_tv_provider.py`, `tests/test_tvdb_provider.py`, `tests/test_fanart_provider.py` + `tests/fixtures/{tmdb,tvdb,fanart}/*.json`.

3. **`tvshow.nfo`, episode NFO, and season artwork writers and readers**
   - Readers: `src/metashelf/readers/kodi_nfo_tv.py` (`read_tvshow_nfo`, `read_episode_nfo` supporting stacked multi-episode `<episodedetails>`).
   - Writers: `src/metashelf/writers/kodi_nfo_tv.py` (`write_tvshow_nfo`, `write_episode_nfo` supporting multi-episode stacked blocks, atomic writes + `.bak`, preserving unknown XML elements).
   - Golden fixtures: `tests/fixtures/nfo/tvshow_golden.nfo`, `tests/fixtures/nfo/episode_golden.nfo`, `tests/fixtures/nfo/multi_episode_golden.nfo`.
   - Tests (first): `tests/test_kodi_nfo_tv.py` (round-trip golden tests, unknown XML preservation, multi-episode `.nfo`, `.bak` creation).

4. **Tree navigation in the detail pane; batch fetch for all episodes of a show**
   - Service: `src/metashelf/services/tv_save.py` (save/revert `tvshow.nfo`, episode NFOs, `match_show_and_fetch_episodes` that matches show once and fetches all seasons/episodes + season posters + episode thumbs).
   - Background job handler: `fetch_show_episodes` in `src/metashelf/jobs/handlers.py`.
   - Router & templates: `src/metashelf/web/routers/tv.py` and `src/metashelf/web/templates/tv/` (`index.html`, `_list.html`, `_detail.html` with Show -> Season -> Episode tree navigation, `_scrape_modal.html`, edit/save/revert/fetch-episodes).
   - Tests: `tests/test_tv_ui.py`, `tests/test_phase2_e2e.py` (multi-season show matched once at show level -> all episode NFOs and thumbs generated).
