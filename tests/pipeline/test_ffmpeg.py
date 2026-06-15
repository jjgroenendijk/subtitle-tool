"""Unit tests for the ffmpeg wrapper that need no ffmpeg binary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from subtitle_tool.pipeline import ffmpeg
from subtitle_tool.pipeline.ffmpeg import (
    FfmpegError,
    FfmpegTimeout,
    MediaProbe,
    SubtitleStream,
)


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


# --- subprocess timeouts: a stalled command must be bounded, not wedge the worker ---


def test_probe_passes_a_timeout_to_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(_args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(_args, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ffmpeg.has_audio_stream(Path("whatever.mkv"))

    assert seen["timeout"] == ffmpeg.PROBE_TIMEOUT_SECONDS


def test_a_stalled_probe_raises_ffmpeg_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def stall(_args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", stall)

    with pytest.raises(FfmpegTimeout, match="timed out"):
        ffmpeg.probe_subtitle_streams(Path("whatever.mkv"))


def test_timeout_is_an_ffmpeg_error_so_callers_keep_going() -> None:
    # Callers tolerate any FfmpegError; a timeout must be one so a stalled file is a
    # warning, not an escape that wedges the run.
    assert issubclass(FfmpegTimeout, FfmpegError)


def test_a_stalled_extract_raises_ffmpeg_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def stall(_args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", stall)

    with pytest.raises(FfmpegTimeout, match="timed out"):
        ffmpeg.extract_subtitle(Path("in.mkv"), 0, Path("out.srt"))


# --- MediaProbe: each video is inspected at most once per run ---


def test_media_probe_caches_audio_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def counting(video: Path) -> bool:
        calls.append(video)
        return True

    monkeypatch.setattr(ffmpeg, "has_audio_stream", counting)
    probe = MediaProbe()
    video = Path("Movie.mkv")

    assert probe.has_audio_stream(video) is True
    assert probe.has_audio_stream(video) is True
    # Two lookups, one underlying probe.
    assert calls == [video]


def test_media_probe_caches_subtitle_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []
    streams = [SubtitleStream(index=2, codec="subrip", language="en")]

    def counting(video: Path) -> list[SubtitleStream]:
        calls.append(video)
        return streams

    monkeypatch.setattr(ffmpeg, "probe_subtitle_streams", counting)
    probe = MediaProbe()
    video = Path("Movie.mkv")

    assert probe.subtitle_streams(video) == streams
    assert probe.subtitle_streams(video) == streams
    assert calls == [video]


def test_media_probe_caches_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    # A corrupt file that times out must be probed once and the same failure re-raised
    # for every later subtitle, not retried (and re-stalled) per file.
    calls: list[Path] = []

    def failing(video: Path) -> bool:
        calls.append(video)
        raise FfmpegTimeout("ffprobe timed out after 60s")

    monkeypatch.setattr(ffmpeg, "has_audio_stream", failing)
    probe = MediaProbe()
    video = Path("Corrupt.mkv")

    with pytest.raises(FfmpegTimeout):
        probe.has_audio_stream(video)
    with pytest.raises(FfmpegTimeout):
        probe.has_audio_stream(video)
    assert calls == [video]


def test_media_probe_keys_on_video_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def counting(video: Path) -> bool:
        calls.append(video)
        return True

    monkeypatch.setattr(ffmpeg, "has_audio_stream", counting)
    probe = MediaProbe()

    probe.has_audio_stream(Path("A.mkv"))
    probe.has_audio_stream(Path("B.mkv"))
    # Distinct videos are each probed once.
    assert calls == [Path("A.mkv"), Path("B.mkv")]
