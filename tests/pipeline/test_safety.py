"""Tests for the temp-file-plus-atomic-replace safety layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from subtitle_tool.pipeline.safety import InvalidResult, resolve_collision, safe_write


def _accept(_: Path) -> None:
    return None


def _reject(_: Path) -> None:
    raise InvalidResult("nope")


def test_safe_write_creates_file_with_content(tmp_path: Path) -> None:
    target = tmp_path / "out.srt"
    result = safe_write(target, "hello\n", validate=_accept)
    assert result == target
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_safe_write_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "out.srt"
    target.write_text("old", encoding="utf-8")
    safe_write(target, "new\n", validate=_accept)
    assert target.read_text(encoding="utf-8") == "new\n"


def test_failed_validation_leaves_original_and_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "out.srt"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(InvalidResult):
        safe_write(target, "bad", validate=_reject)
    assert target.read_text(encoding="utf-8") == "original"
    # No temporary files were left behind in the directory.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.srt"]


def test_resolve_collision_returns_target_when_free(tmp_path: Path) -> None:
    target = tmp_path / "movie.en.srt"
    assert resolve_collision(target) == target


def test_resolve_collision_appends_numeric_suffix(tmp_path: Path) -> None:
    target = tmp_path / "movie.en.srt"
    target.write_text("", encoding="utf-8")
    assert resolve_collision(target) == tmp_path / "movie.en (1).srt"

    (tmp_path / "movie.en (1).srt").write_text("", encoding="utf-8")
    assert resolve_collision(target) == tmp_path / "movie.en (2).srt"
