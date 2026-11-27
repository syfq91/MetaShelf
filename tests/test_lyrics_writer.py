"""Tests for lyrics writer: .lrc, .txt, no-overwrite, and .bak (written first)."""

from pathlib import Path

import pytest

from metashelf.writers.lyrics import LyricsExistsError, write_lyrics_file


def test_write_lyrics_lrc_and_txt_with_no_overwrite(tmp_path: Path) -> None:
    track = tmp_path / "01 - One More Time.mp3"
    track.write_bytes(b"audio")

    out_lrc = write_lyrics_file(track, "[00:45.10] One more time\n", synced=True)
    assert out_lrc.name == "01 - One More Time.lrc"
    assert "[00:45.10]" in out_lrc.read_text(encoding="utf-8")

    with pytest.raises(LyricsExistsError):
        write_lyrics_file(track, "new", synced=True, overwrite=False)

    write_lyrics_file(track, "updated", synced=True, overwrite=True)
    assert (tmp_path / "01 - One More Time.lrc.bak").exists()

    out_txt = write_lyrics_file(track, "Plain lyrics", synced=False)
    assert out_txt.name == "01 - One More Time.txt"
