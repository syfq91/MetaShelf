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
3. **Movie Details + Credits + Release Dates**: `GET /3/movie/{movie_id}?append_to_response=credits,release_dates`
   - Params: `api_key`, `language`, `append_to_response=credits,release_dates`.
   - Response fields: `id`, `imdb_id`, `title`, `original_title`, `release_date`, `tagline`, `overview`, `runtime`, `vote_average`, `vote_count`, `genres[].name`, `production_companies[].name`, `production_countries[].name`, `belongs_to_collection.name`, `credits.cast[]` (`name`, `character`, `order`, `profile_path`), `credits.crew[]` (`name`, `job`, `department`), `release_dates.results[]` (`iso_3166_1`, `release_dates[].certification`, `release_dates[].type`).
4. **Movie Images**: `GET /3/movie/{movie_id}/images`
   - Params: `api_key`, `include_image_language` (e.g. `en,null`).
   - Response: `posters[]`, `backdrops[]` with `file_path`, `width`, `height`, `iso_639_1`, `vote_average`.

### Rate Limits & Attribution
- TMDB enforces rate limits (~30-40 requests per 10 seconds). MetaShelf enforces a conservative token-bucket / interval rate limiter (e.g. 3 requests/sec) and caches responses in `provider_cache`.
- Attribution requirement: UI Settings / About must include: *"This product uses the TMDB API but is not endorsed or certified by TMDB."*

### Endpoints Used (TV Shows)
1. **Search TV**: `GET /3/search/tv` (`query`, `first_air_date_year`, `language`, `include_adult=false`).
2. **Series Details**: `GET /3/tv/{series_id}?append_to_response=credits,external_ids,content_ratings` (`name`, `original_name`, `first_air_date`, `overview`, `status`, `vote_average`, `vote_count`, `genres`, `networks`, `seasons[]`, `external_ids.tvdb_id`, `external_ids.imdb_id`, `credits`).
3. **Season Details (Episodes)**: `GET /3/tv/{series_id}/season/{season_number}` -> `episodes[]` (`episode_number`, `season_number`, `name`, `overview`, `air_date`, `runtime`, `still_path`, `vote_average`, `vote_count`, `crew[]`, `guest_stars[]`).
4. **TV Images**: `GET /3/tv/{series_id}/images` (`posters[]`, `backdrops[]`) and `GET /3/tv/{series_id}/season/{season_number}/images` (`posters[]`).

---

## TheTVDB API v4 (Optional TV Provider)

Source: Official TheTVDB v4 API (`thetvdb.github.io/v4-api`), verified 2026-11-27.

- **Base URL**: `https://api4.thetvdb.com/v4`
- **Authentication**: `POST /login` with `{"apikey": "..."}` returns a JWT (`data.token`), passed as `Authorization: Bearer <token>`.
- **Search**: `GET /search?query=...&type=series`
- **Series Details**: `GET /series/{id}/extended`
- **Episodes**: `GET /series/{id}/episodes/default?page=0` (and `/series/{id}/episodes/official/{lang}`)

---

## fanart.tv API v3 (Extra Artwork)

Source: Official fanart.tv API v3 (`fanarttv.docs.apiary.io`), verified 2026-11-27.

- **Base URL**: `https://webservice.fanart.tv/v3/tv/{tvdb_id}`
- **Authentication**: `api_key` query param or `api-key` header (plus optional `client-key`).
- **TV Image Arrays**: `tvposter` (`poster`), `showbackground` (`fanart`), `tvbanner` (`banner`), `hdtvlogo` / `clearlogo` (`logo`), `seasonposter` (with `season` field).

---

## MusicBrainz API v2

Source: Official MusicBrainz WS/2 documentation (`musicbrainz.org/doc/MusicBrainz_API`), verified 2026-11-27.

- **Base URL**: `https://musicbrainz.org/ws/2`
- **Format**: `fmt=json` query parameter (or `Accept: application/json`).
- **Authentication**: None (no API key), but a **descriptive `User-Agent` header** is mandatory (e.g. `MetaShelf/0.1.0 (https://github.com/syfq91/MetaShelf)`), otherwise requests receive `403`/`503`.
- **Rate Limit**: Strict **1 request per second** per IP (`AsyncRateLimiter(calls_per_second=1.0)`).
- **Endpoints Used**:
  - `GET /ws/2/artist?query=...&fmt=json` -> `artists[]` (`id`, `name`, `sort-name`, `type`, `disambiguation`, `life-span`, `tags[]`)
  - `GET /ws/2/artist/{mbid}?inc=release-groups+tags&fmt=json`
  - `GET /ws/2/release?query=...&fmt=json` -> `releases[]` (`id`, `title`, `date`, `country`, `track-count`, `media[].track-count`, `release-group.id`, `artist-credit[]`, `label-info[]`)
  - `GET /ws/2/release/{mbid}?inc=recordings+artists+release-groups+labels+tags&fmt=json` -> `media[].tracks[]` (`position`, `title`, `length`)

---

## Cover Art Archive API

Source: Official Cover Art Archive documentation (`coverartarchive.org`), verified 2026-11-27.

- **Base URL**: `https://coverartarchive.org`
- **Authentication**: None required.
- **Redirects**: Endpoints return `307 Temporary Redirect` to Internet Archive storage; HTTP client must follow redirects when fetching JSON/images.
- **Endpoints Used**:
  - `GET /release/{mbid}` -> `images[]` (`front`, `back`, `types[]`, `image`, `thumbnails.500` / `thumbnails.1200`)
  - `GET /release-group/{mbid}` -> fallback if release has no cover art.

---

## Open Library API

Source: Official Open Library Developer Documentation (`openlibrary.org/developers/api`), verified 2026-11-27.

- **Base URL**: `https://openlibrary.org`
- **Authentication**: None required; supply a descriptive `User-Agent` header.
- **Endpoints Used**:
  - `GET /search.json?isbn=...` or `?title=...&author=...` -> `docs[]` (`key`, `title`, `author_name[]`, `first_publish_year`, `publisher[]`, `isbn[]`, `subject[]`, `cover_i`).
  - `GET /isbn/{isbn}.json` -> edition details (`title`, `publishers[]`, `publish_date`, `isbn_13[]`, `isbn_10[]`, `works[].key`, `covers[]`).
  - `GET {work_key}.json` -> `description` (string or `{"value": "..."}`), `subjects[]`.
- **Covers API**: `https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false` or `https://covers.openlibrary.org/b/id/{cover_i}-L.jpg?default=false`.

---

## Google Books API v1

Source: Official Google Books API v1 documentation (`developers.google.com/books/docs/v1/using`), verified 2026-11-27.

- **Base URL**: `https://www.googleapis.com/books/v1`
- **Authentication**: Optional `key` query parameter (`METASHELF_GOOGLE_BOOKS_API_KEY`).
- **Endpoints Used**:
  - `GET /volumes?q=isbn:{isbn}` or `q=intitle:{title}+inauthor:{author}` -> `items[]` (`id`, `volumeInfo`: `title`, `authors[]`, `publisher`, `publishedDate`, `description`, `industryIdentifiers[]`, `categories[]`, `language`, `imageLinks.thumbnail`).
  - `GET /volumes/{volume_id}` -> full volume details.
- **Note**: Replace `http://` with `https://` on `imageLinks` URLs.
