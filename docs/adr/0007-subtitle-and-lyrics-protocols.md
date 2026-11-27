# ADR 0007: SubtitleProvider and LyricsProvider Protocols

## Status
Accepted

## Context
Phase 6 introduces subtitles (movies and episodes) and lyrics (music tracks). Per `docs/PLAN.md` section 6, subtitles and lyrics use their own small protocols alongside `Provider`.

## Decision
- Add `SubtitleQuery`, `SubtitleCandidate`, `SubtitleDownload`, `SubtitleProvider`, `LyricsQuery`, `LyricsCandidate`, and `LyricsProvider` to `src/metashelf/providers/base.py` without modifying the existing `Provider` protocol.
- Track downloaded subtitle and lyrics sidecars in the existing `sidecar_file` table (`kind` in `"subtitle"`, `"lyrics"`, storing `lang`, `format`, `synced`, `source`, `source_id`, `sha256`).
