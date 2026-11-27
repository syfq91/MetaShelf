"""Tests for subtitle writer: naming, UTF-8 conversion, no-overwrite, and .bak (written first)."""

from pathlib import Path

import pytest

from metashelf.writers.subtitles import (
    SubtitleExistsError,
    subtitle_target_path,
    write_subtitle_file,
)


def test_subtitle_target_path_naming(tmp_path: Path) -> None:
    video = tmp_path / "Inception (2010).mkv"
    assert subtitle_target_path(video, "en").name == "Inception (2010).en.srt"
    assert subtitle_target_path(video, "en", forced=True).name == "Inception (2010).en.forced.srt"
    assert (
        subtitle_target_path(video, "en", hearing_impaired=True).name
        == "Inception (2010).en.sdh.srt"
    )


def test_write_subtitle_converts_cp1252_to_utf8_and_respects_no_overwrite(tmp_path: Path) -> None:
    video = tmp_path / "Amelie (2001).mkv"
    video.write_bytes(b"video")

    # CP1252 encoded French subtitle ("Café")
    cp1252_bytes = "1\n00:00:01,000 --> 00:00:02,000\nCafé\n".encode("cp1252")
    out = write_subtitle_file(video, "fr", cp1252_bytes)
    assert out.name == "Amelie (2001).fr.srt"
    assert out.read_text(encoding="utf-8") == "1\n00:00:01,000 --> 00:00:02,000\nCafé\n"

    # Existing file is never overwritten unless overwrite=True
    with pytest.raises(SubtitleExistsError):
        write_subtitle_file(video, "fr", b"new-sub", overwrite=False)

    # With overwrite=True, creates .bak before overwriting
    write_subtitle_file(video, "fr", b"new-sub", overwrite=True)
    assert out.read_text(encoding="utf-8") == "new-sub"
    assert (tmp_path / "Amelie (2001).fr.srt.bak").read_text(
        encoding="utf-8"
    ) == "1\n00:00:01,000 --> 00:00:02,000\nCafé\n"
