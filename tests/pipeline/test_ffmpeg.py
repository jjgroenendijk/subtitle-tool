"""Unit tests for the ffmpeg wrapper that need no ffmpeg binary."""

from __future__ import annotations

from pathlib import Path

import pytest

from subtitle_tool.pipeline import ffmpeg
from subtitle_tool.pipeline.ffmpeg import FfmpegError, SubtitleStream


def test_text_codecs_are_classified_as_text() -> None:
    assert SubtitleStream(index=0, codec="subrip").is_text
    assert SubtitleStream(index=0, codec="ass").is_text
    assert SubtitleStream(index=0, codec="mov_text").is_text


def test_image_codecs_are_not_text() -> None:
    # PGS and DVD/VOBSUB streams are image-based and must be left embedded.
    assert not SubtitleStream(index=0, codec="hdmv_pgs_subtitle").is_text
    assert not SubtitleStream(index=0, codec="dvd_subtitle").is_text
    assert not SubtitleStream(index=0, codec="dvb_subtitle").is_text


def test_missing_binary_raises_ffmpeg_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg, "FFPROBE", "definitely-not-a-real-binary-xyz")

    with pytest.raises(FfmpegError, match="not found"):
        ffmpeg.probe_subtitle_streams(Path("whatever.mkv"))
