# Open Questions & Safe Defaults

1. **TMDB MPAA / Certification in `/movie/{id}`**:
   - TMDB stores per-country certifications in `/movie/{id}/release_dates`, not directly on `/movie/{id}`.
   - *Default:* For Phase 1, leave `mpaa` editable in the UI and preserved in NFO; optionally parse `release_dates` if included in `append_to_response` when available in fixtures.
2. **NFO `<set>` tag format**:
   - Kodi 17+ uses `<set><name>...</name></set>`, while older tools wrote `<set>...</set>`.
   - *Default:* Reader accepts both; writer emits `<set><name>...</name></set>`.
