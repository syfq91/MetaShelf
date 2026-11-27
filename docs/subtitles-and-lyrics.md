# Subtitles & Lyrics Sidecar Format Notes

## External Subtitles (Kodi & Jellyfin)
Source: Jellyfin & Kodi external subtitle naming documentation, verified 2026-11-27.

- **Standard**: `<video filename>.<lang>.srt` (e.g. `Inception (2010).en.srt`).
- **Flags**: `<video filename>.<lang>.forced.srt` (forced) or `<video filename>.<lang>.sdh.srt` (hearing-impaired / SDH). Language code always precedes flags.
- **Encoding**: Convert downloaded subtitle bytes to UTF-8 (trying UTF-8-SIG, UTF-8, CP1252, Latin-1) before saving.
- **Safety**: Never overwrite an existing subtitle file unless explicitly forced (and always keep `.bak` before overwriting via `atomic_write_bytes`).

## OpenSubtitles 64-bit Movie Hash
- Sum of: file size in bytes + 64-bit little-endian unsigned integers from the first 64 KiB and last 64 KiB of the video file, masked to 64 bits (`& 0xFFFFFFFFFFFFFFFF`), formatted as 16 lowercase hex digits.
- For files smaller than 128 KiB, fallback gracefully to ID/title search without crashing.

## Lyrics (Music Tracks)
- **Time-synced**: `<track filename>.lrc` (LRC format with `[mm:ss.xx]` timestamps).
- **Plain text fallback**: `<track filename>.txt`.
- Saved next to the audio file in UTF-8. Never overwrite an existing lyrics file in only-missing mode; keep `.bak` if forced.
