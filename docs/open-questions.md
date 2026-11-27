# Open Questions & Safe Defaults

1. **TMDB MPAA / Certification in `/movie/{id}`** *(Resolved)*:
   - TMDB stores per-country certifications in `/movie/{id}/release_dates` (`results[].iso_3166_1`, `release_dates[].certification`).
   - *Decision:* Bundle `release_dates` via `append_to_response=credits,release_dates` in `TMDBProvider.fetch()`, extract the certification for the language's region (defaulting to `US`, falling back to the first non-empty certification), and populate `MovieMetadata.mpaa`. Remains editable in the UI.
2. **NFO `<set>` tag format**:
   - Kodi 17+ uses `<set><name>...</name></set>`, while older tools wrote `<set>...</set>`.
   - *Default:* Reader accepts both; writer emits `<set><name>...</name></set>`.
