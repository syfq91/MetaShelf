# Provider Documentation Notes

## TMDB (The Movie Database) API v3

Source: Official TMDB API v3 documentation (`developer.themoviedb.org`), verified 2026-11-27.

### Authentication
- API Key (`api_key` query parameter) or Bearer Access Token. MetaShelf uses `api_key` query param so users can paste a standard TMDB v3 API key.
- Missing API key must raise a clear `MissingApiKeyError` surfaced in the UI/Jobs.

### Endpoints Used (Movies)
1. **Configuration**: `GET /3/configuration` -> `images.secure_base_url`, `images.poster_sizes`, `images.backdrop_sizes`. Default fallback if config not fetched: `https://image.tmdb.org/t/p/`.
2. **Search Movie**: `GET /3/search/movie`
   - Params: `api_key`, `query`, `year` (optional), `language` (e.g. `en-US`), `include_adult=false`.
   - Response: `results[]` with `id`, `title`, `original_title`, `release_date`, `overview`, `poster_path`, `backdrop_path`, `popularity`, `vote_average`, `vote_count`.
3. **Movie Details + Credits**: `GET /3/movie/{movie_id}?append_to_response=credits`
   - Params: `api_key`, `language`, `append_to_response=credits`.
   - Response fields: `id`, `imdb_id`, `title`, `original_title`, `release_date`, `tagline`, `overview`, `runtime`, `vote_average`, `vote_count`, `genres[].name`, `production_companies[].name`, `production_countries[].name`, `belongs_to_collection.name`, `credits.cast[]` (`name`, `character`, `order`, `profile_path`), `credits.crew[]` (`name`, `job`, `department`).
4. **Movie Images**: `GET /3/movie/{movie_id}/images`
   - Params: `api_key`, `include_image_language` (e.g. `en,null`).
   - Response: `posters[]`, `backdrops[]` with `file_path`, `width`, `height`, `iso_639_1`, `vote_average`.

### Rate Limits & Attribution
- TMDB enforces rate limits (~30-40 requests per 10 seconds). MetaShelf enforces a conservative token-bucket / interval rate limiter (e.g. 3 requests/sec) and caches responses in `provider_cache`.
- Attribution requirement: UI Settings / About must include: *"This product uses the TMDB API but is not endorsed or certified by TMDB."*
