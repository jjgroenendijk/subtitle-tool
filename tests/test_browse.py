"""Tests for the directory-browsing helper backing the media-path picker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_tool.web.browse import browse

if TYPE_CHECKING:
    from pathlib import Path


def test_browse_lists_subdirectories_sorted_and_skips_hidden(tmp_path: Path) -> None:
    (tmp_path / "Bravo").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "a-file.txt").write_text("x", encoding="utf-8")

    result = browse(tmp_path, None)

    assert result.status_code == 200
    names = [entry["name"] for entry in result.body["entries"]]
    # Case-insensitive sort, files and dot-directories excluded.
    assert names == ["alpha", "Bravo"]
    assert result.body["parent"] is None
    assert result.body["path"] == str(tmp_path.resolve())


def test_browse_reports_parent_when_inside_root(tmp_path: Path) -> None:
    child = tmp_path / "movies"
    child.mkdir()

    result = browse(tmp_path, str(child))

    assert result.status_code == 200
    assert result.body["parent"] == str(tmp_path.resolve())


def test_browse_rejects_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()

    result = browse(root, str(tmp_path))

    assert result.status_code == 400
    assert "outside" in result.body["error"]


def test_browse_404_for_missing_directory(tmp_path: Path) -> None:
    result = browse(tmp_path, str(tmp_path / "nope"))

    assert result.status_code == 404
    assert "not a directory" in result.body["error"]
