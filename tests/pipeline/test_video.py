"""Tests for the video phase: ffprobe inspection, extraction, and remux.

Fixture videos are generated with ffmpeg in test setup: a tiny black clip plus one
text subtitle stream per requested language. The whole module is skipped where
ffmpeg/ffprobe are not on PATH so the rest of the suite still runs locally.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which

import pytest

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline import ffmpeg, run_pipeline
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.video import process_video
from subtitle_tool.scanner import scan

pytestmark = pytest.mark.skipif(
    which("ffmpeg") is None or which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)

# Enough dialogue per language for confident detection once extracted.
_SRT_BY_LANG = {
    "eng": (
        "1\n00:00:00,500 --> 00:00:02,000\n"
        "Good morning everyone, I hope you all slept well last night.\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\n"
        "We have a very long day ahead of us, so let us begin right away.\n"
    ),
    "fre": (
        "1\n00:00:00,500 --> 00:00:02,000\n"
        "Bonjour tout le monde, j'espere que vous avez bien dormi cette nuit.\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\n"
        "Nous avons une tres longue journee devant nous, alors commencons.\n"
    ),
    "dut": (
        "1\n00:00:00,500 --> 00:00:02,000\n"
        "Goedemorgen allemaal, ik hoop dat jullie vannacht goed geslapen hebben.\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\n"
        "We hebben een hele lange dag voor de boeg, dus laten we meteen beginnen.\n"
    ),
}
_GENERIC_SRT = "1\n00:00:00,500 --> 00:00:02,000\nGeneric subtitle line.\n"


def _build_video(path: Path, languages: list[str], *, fmt: str | None = None) -> Path:
    """Create an mkv at ``path`` with one text subtitle stream per language code.

    ``fmt`` forces the output container, letting a caller write matroska content under
    a non-matroska name (AVI cannot itself carry text subtitle streams).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    srt_paths: list[Path] = []
    for i, lang in enumerate(languages):
        srt = path.parent / f"._src_{lang}_{i}.srt"
        srt.write_text(_SRT_BY_LANG.get(lang, _GENERIC_SRT), encoding="utf-8")
        srt_paths.append(srt)

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x48:d=2",
    ]
    for srt in srt_paths:
        cmd += ["-i", str(srt)]
    cmd += ["-map", "0:v"]
    for i in range(len(languages)):
        cmd += ["-map", f"{i + 1}:0"]
    cmd += ["-c:v", "mpeg4", "-c:s", "srt"]
    for i, lang in enumerate(languages):
        cmd += [f"-metadata:s:s:{i}", f"language={lang}"]
    if fmt is not None:
        cmd += ["-f", fmt]
    cmd.append(str(path))
    subprocess.run(cmd, check=True, capture_output=True)

    for srt in srt_paths:
        srt.unlink()
    return path


def _config(tmp_path: Path, **extraction: object) -> Config:
    return Config.model_validate(
        {"scan": {"media_paths": [str(tmp_path)]}, "extraction": {"enabled": True, **extraction}}
    )


def test_probe_reports_text_streams_with_languages(tmp_path: Path) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng", "fre"])

    streams = ffmpeg.probe_subtitle_streams(video)

    assert [(s.codec, s.language, s.is_text) for s in streams] == [
        ("subrip", "eng", True),
        ("subrip", "fre", True),
    ]


def test_extraction_writes_external_srt_files(tmp_path: Path) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng", "fre"])

    result, extracted = process_video(video, _config(tmp_path), dry_run=False)

    assert {p.name for p in extracted} == {"Movie (2020).en.srt", "Movie (2020).fr.srt"}
    for path in extracted:
        assert path.exists()
    assert result is not None
    assert [a.type for a in result.actions] == [
        ActionType.EXTRACT_SUBTITLE,
        ActionType.EXTRACT_SUBTITLE,
    ]


def test_disabled_extraction_does_nothing(tmp_path: Path) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng"])
    config = Config.model_validate({"scan": {"media_paths": [str(tmp_path)]}})

    result, extracted = process_video(video, config, dry_run=False)

    assert result is None
    assert extracted == []


def test_no_text_streams_is_a_noop(tmp_path: Path) -> None:
    # A video with no subtitle streams at all yields nothing to extract.
    path = tmp_path / "Silent (2021).mkv"
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x48:d=1",
            "-c:v",
            "mpeg4",
            str(path),
        ],
        check=True,
        capture_output=True,
    )

    result, extracted = process_video(path, _config(tmp_path), dry_run=False)

    assert result is None
    assert extracted == []


def test_language_filter_extracts_only_wanted(tmp_path: Path) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng", "fre", "dut"])

    _result, extracted = process_video(
        video, _config(tmp_path, languages=["en", "nl"]), dry_run=False
    )

    assert {p.name for p in extracted} == {"Movie (2020).en.srt", "Movie (2020).nl.srt"}


def test_dry_run_plans_extraction_without_writing(tmp_path: Path) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng"])

    result, extracted = process_video(video, _config(tmp_path), dry_run=True)

    assert extracted == []
    assert not (tmp_path / "Movie (2020).en.srt").exists()
    assert result is not None
    assert result.actions[0].type is ActionType.EXTRACT_SUBTITLE


def test_extraction_does_not_overwrite_existing_subtitle(tmp_path: Path) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng"])
    existing = tmp_path / "Movie (2020).en.srt"
    existing.write_text("keep me", encoding="utf-8")

    _result, extracted = process_video(video, _config(tmp_path), dry_run=False)

    assert existing.read_text(encoding="utf-8") == "keep me"
    assert extracted == [tmp_path / "Movie (2020).en (1).srt"]


def test_remux_keeps_original_and_drops_streams_by_default(tmp_path: Path) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng"])

    result, _extracted = process_video(
        tmp_path / "Movie (2020).mkv", _config(tmp_path, remux=True), dry_run=False
    )

    assert video.exists()  # original kept by default
    remuxed = tmp_path / "Movie (2020).remuxed.mkv"
    assert remuxed.exists()
    # The remuxed copy carries no subtitle streams; the original still does.
    assert ffmpeg.probe_subtitle_streams(remuxed) == []
    assert len(ffmpeg.probe_subtitle_streams(video)) == 1
    assert result is not None
    assert ActionType.REMUX in {a.type for a in result.actions}
    assert ActionType.DELETE_ORIGINAL not in {a.type for a in result.actions}


def test_remux_with_delete_replaces_original_in_place(tmp_path: Path) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng"])

    result, _extracted = process_video(
        video, _config(tmp_path, remux=True, delete_original_video=True), dry_run=False
    )

    assert not (tmp_path / "Movie (2020).remuxed.mkv").exists()
    assert video.exists()  # same path, now without the extracted stream
    assert ffmpeg.probe_subtitle_streams(video) == []
    assert result is not None
    assert {ActionType.REMUX, ActionType.DELETE_ORIGINAL} <= {a.type for a in result.actions}


def test_avi_is_never_remuxed(tmp_path: Path) -> None:
    avi = _build_video(tmp_path / "Movie (2020).avi", ["eng"], fmt="matroska")

    result, _extracted = process_video(avi, _config(tmp_path, remux=True), dry_run=False)

    assert not (tmp_path / "Movie (2020).remuxed.avi").exists()
    assert result is not None
    assert any("AVI" in w for w in result.warnings)
    assert ActionType.REMUX not in {a.type for a in result.actions}


def test_failed_remux_leaves_original_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng"])
    before = video.read_bytes()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise ffmpeg.FfmpegError("simulated ffmpeg crash")

    monkeypatch.setattr(ffmpeg, "remux_without_streams", boom)

    result, _extracted = process_video(video, _config(tmp_path, remux=True), dry_run=False)

    assert video.read_bytes() == before
    assert not (tmp_path / "Movie (2020).remuxed.mkv").exists()
    # No leftover temp files from the aborted remux.
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
    assert result is not None
    assert any("remux failed" in w for w in result.warnings)


def test_remux_aborts_when_source_changes_midway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng"])
    before = video.read_bytes()

    def touch_source_then_write(_video: Path, _drop: list[int], target: Path) -> None:
        # Simulate the source being rewritten while ffmpeg ran.
        video.write_bytes(before + b"changed")
        target.write_bytes(b"remuxed output")

    monkeypatch.setattr(ffmpeg, "remux_without_streams", touch_source_then_write)

    result, _extracted = process_video(video, _config(tmp_path, remux=True), dry_run=False)

    assert not (tmp_path / "Movie (2020).remuxed.mkv").exists()
    assert result is not None
    assert any("changed during remux" in w for w in result.warnings)


def test_extracted_subtitles_flow_through_the_pipeline(tmp_path: Path) -> None:
    # A full run: the English stream is extracted and the resulting SRT is then
    # processed like any other subtitle (detection confirms the language code).
    _build_video(tmp_path / "Movie (2020).mkv", ["eng"])
    config = _config(tmp_path)

    result = run_pipeline(scan(config), config, dry_run=False)

    extracted = tmp_path / "Movie (2020).en.srt"
    assert extracted.exists()
    sources = {r.source.name for r in result.file_results}
    # Both the video row (with the extract action) and the extracted subtitle appear.
    assert "Movie (2020).mkv" in sources
    assert extracted.name in sources
    video_result = next(r for r in result.file_results if r.source.name == "Movie (2020).mkv")
    assert ActionType.EXTRACT_SUBTITLE in {a.type for a in video_result.actions}


def test_dry_run_pipeline_plans_extraction_without_writing(tmp_path: Path) -> None:
    _build_video(tmp_path / "Movie (2020).mkv", ["eng"])
    config = _config(tmp_path)

    result = run_pipeline(scan(config), config, dry_run=True)

    assert not (tmp_path / "Movie (2020).en.srt").exists()
    video_result = next(r for r in result.file_results if r.source.name == "Movie (2020).mkv")
    assert ActionType.EXTRACT_SUBTITLE in {a.type for a in video_result.actions}


def test_remux_skipped_when_disk_space_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    video = _build_video(tmp_path / "Movie (2020).mkv", ["eng"])
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: type("U", (), {"free": 1})())

    result, _extracted = process_video(video, _config(tmp_path, remux=True), dry_run=False)

    assert not (tmp_path / "Movie (2020).remuxed.mkv").exists()
    assert result is not None
    assert any("free disk space" in w for w in result.warnings)
