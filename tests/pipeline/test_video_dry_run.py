"""Dry-run planning of the video phase, isolated from a real ffmpeg.

These tests stub ``ffmpeg.probe_subtitle_streams`` so they exercise the planning
logic without invoking ffmpeg, and so run even where ffmpeg is not installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline import ffmpeg
from subtitle_tool.pipeline.video import process_video

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _config(tmp_path: Path, **extraction: object) -> Config:
    return Config.model_validate(
        {"scan": {"media_paths": [str(tmp_path)]}, "extraction": {"enabled": True, **extraction}}
    )


def test_dry_run_suffixes_duplicate_planned_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two English text streams both map to Movie.en.srt; a real run would suffix the
    # second, so the dry run must plan distinct targets rather than the same name twice.
    video = tmp_path / "Movie.mkv"
    streams = [
        ffmpeg.SubtitleStream(index=2, codec="subrip", language="eng"),
        ffmpeg.SubtitleStream(index=3, codec="subrip", language="eng"),
    ]
    monkeypatch.setattr(ffmpeg, "probe_subtitle_streams", lambda _video: streams)

    result, extracted = process_video(video, _config(tmp_path), dry_run=True)

    assert extracted == []
    assert result is not None
    descriptions = [a.description for a in result.actions]
    assert descriptions == [
        "extract stream 2 (eng) to Movie.en.srt",
        "extract stream 3 (eng) to Movie.en (1).srt",
    ]


def test_dry_run_suffixes_against_existing_file_and_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An existing Movie.en.srt plus two English streams: the first plan takes the (1)
    # slot already on disk, the second must step past both to (2).
    video = tmp_path / "Movie.mkv"
    (tmp_path / "Movie.en.srt").write_text("keep me", encoding="utf-8")
    streams = [
        ffmpeg.SubtitleStream(index=2, codec="subrip", language="eng"),
        ffmpeg.SubtitleStream(index=3, codec="subrip", language="eng"),
    ]
    monkeypatch.setattr(ffmpeg, "probe_subtitle_streams", lambda _video: streams)

    result, _extracted = process_video(video, _config(tmp_path), dry_run=True)

    assert result is not None
    descriptions = [a.description for a in result.actions]
    assert descriptions == [
        "extract stream 2 (eng) to Movie.en (1).srt",
        "extract stream 3 (eng) to Movie.en (2).srt",
    ]
