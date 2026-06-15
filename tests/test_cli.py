"""Tests for the command-line interface."""

from __future__ import annotations

from pathlib import Path

import pytest

from subtitle_tool.cli import main

DIRTY = "1\n00:00:01,000 --> 00:00:04,000\nSubtitles by OpenSubtitles\nReal\n"


def _library(root: Path) -> None:
    (root / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    (root / "Movie (2020).en.srt").write_bytes(DIRTY.encode("windows-1252"))


def test_scan_dry_run_reports_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _library(tmp_path)
    before = (tmp_path / "Movie (2020).en.srt").read_bytes()

    exit_code = main(["scan", str(tmp_path), "--dry-run"])

    assert exit_code == 0
    assert (tmp_path / "Movie (2020).en.srt").read_bytes() == before
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "cleanup" in out


def test_scan_real_run_writes_changes(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _library(tmp_path)

    exit_code = main(["scan", str(tmp_path)])

    assert exit_code == 0
    cleaned = (tmp_path / "Movie (2020).en.srt").read_text(encoding="utf-8")
    assert "OpenSubtitles" not in cleaned
    assert "Real" in cleaned
    assert "real" in capsys.readouterr().out


def test_scan_real_run_reports_skipped_write(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # A broken-only SRT whose cleanup result fails validation: the original is left
    # untouched, so the report must show it skipped rather than counted as changed.
    (tmp_path / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    path = tmp_path / "Movie (2020).en.srt"
    broken = "this is a broken block with no timing\n"
    path.write_text(broken, encoding="utf-8")

    exit_code = main(["scan", str(tmp_path)])

    assert exit_code == 0
    assert path.read_text(encoding="utf-8") == broken  # nothing written
    out = capsys.readouterr().out
    assert "0 file(s) changed" in out
    assert "skipped (left untouched)" in out
    assert "planned [cleanup]" in out


def test_scan_with_no_paths_and_missing_config_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    exit_code = main(["scan", "--config", str(tmp_path / "missing.toml")])

    assert exit_code == 2
    assert "[ERROR]" in capsys.readouterr().out


def test_scan_loads_media_paths_from_config_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    _library(media)
    config_file = tmp_path / "config.toml"
    config_file.write_text(f'[scan]\nmedia_paths = ["{media}"]\n', encoding="utf-8")

    exit_code = main(["scan", "--config", str(config_file), "--dry-run"])

    assert exit_code == 0
    assert "would change" in capsys.readouterr().out
