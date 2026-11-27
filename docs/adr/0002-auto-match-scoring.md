# ADR 0002: Auto-Match Confidence Scoring

## Status
Accepted

## Context
Auto-matching media files to online providers must avoid false positives while handling minor punctuation/year differences, and must never overwrite manual user choices.

## Decision
- **Scoring**: Combine normalized title similarity (`difflib.SequenceMatcher`, weight 0.70) with release year proximity (exact: +0.30, ±1 year or unknown query year: +0.15, mismatch: 0.0).
- **Acceptance**: Auto-accept the top candidate only when `top_score >= 0.80` and `(top_score - second_score) >= 0.15` (or there is only one candidate). Otherwise leave the item `unmatched` for manual selection in the Scrape modal.
- **Immutability of choices**: Items with existing provider IDs or `dirty` state are skipped by auto-match and re-scans.
