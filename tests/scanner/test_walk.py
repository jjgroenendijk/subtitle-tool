"""Tests for directory walking, classification, and exclude patterns."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.scanner.walk import is_subtitle, is_video, iter_files


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_classification_is_case_insensitive() -> None:
    assert is_video(Path("a.MKV"))
    assert is_video(Path("a.mp4"))
    assert not is_video(Path("a.srt"))
    assert is_subtitle(Path("a.SRT"))
    assert is_subtitle(Path("a.ass"))
    assert not is_subtitle(Path("a.mkv"))
    # Image-based subtitles are not handled.
    assert not is_subtitle(Path("a.sup"))
    assert not is_subtitle(Path("a.idx"))


def test_iter_files_walks_recursively_in_sorted_order(tmp_path: Path) -> None:
    _touch(tmp_path / "b.mkv")
    _touch(tmp_path / "a.mkv")
    _touch(tmp_path / "sub" / "c.srt")

    found = [p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, [])]

    assert found == ["a.mkv", "b.mkv", "sub/c.srt"]


def test_iter_files_non_recursive_yields_only_top_level(tmp_path: Path) -> None:
    _touch(tmp_path / "b.mkv")
    _touch(tmp_path / "a.mkv")
    _touch(tmp_path / "sub" / "c.srt")

    found = [p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, [], recursive=False)]

    # Files directly in the root are yielded; nothing under a subdirectory is.
    assert found == ["a.mkv", "b.mkv"]


def test_iter_files_non_recursive_still_applies_excludes(tmp_path: Path) -> None:
    _touch(tmp_path / "keep.mkv")
    _touch(tmp_path / "scratch.tmp")

    found = {
        p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, ["*.tmp"], recursive=False)
    }

    assert found == {"keep.mkv"}


def test_exclude_pattern_prunes_directory(tmp_path: Path) -> None:
    _touch(tmp_path / "keep.mkv")
    _touch(tmp_path / "Sample" / "sample.mkv")
    _touch(tmp_path / "nested" / "Sample" / "deep.mkv")

    found = {p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, ["Sample"])}

    assert found == {"keep.mkv"}


def test_exclude_pattern_matches_filename_glob(tmp_path: Path) -> None:
    _touch(tmp_path / "keep.mkv")
    _touch(tmp_path / "scratch.tmp")
    _touch(tmp_path / "sub" / "note.tmp")

    found = {p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, ["*.tmp"])}

    assert found == {"keep.mkv"}


def test_exclude_pattern_matches_relative_path(tmp_path: Path) -> None:
    _touch(tmp_path / "keep.mkv")
    _touch(tmp_path / "private" / "secret.mkv")

    found = {p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, ["private/*"])}

    assert found == {"keep.mkv"}


def test_trailing_slash_in_pattern_is_ignored(tmp_path: Path) -> None:
    _touch(tmp_path / "keep.mkv")
    _touch(tmp_path / "Subs" / "x.srt")

    found = {p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, ["Subs/"])}

    assert found == {"keep.mkv"}


def test_double_star_excludes_root_and_nested_directories(tmp_path: Path) -> None:
    _touch(tmp_path / "keep.mkv")
    _touch(tmp_path / "Show" / "sample" / "clip.mkv")
    _touch(tmp_path / "sample" / "top.mkv")

    found = [p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, ["**/sample/**"])]

    assert found == ["keep.mkv"]


def test_single_star_does_not_cross_directory_separator(tmp_path: Path) -> None:
    _touch(tmp_path / "a" / "b.mkv")
    _touch(tmp_path / "a" / "sub" / "c.mkv")

    found = {p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, ["a/*.mkv"])}

    assert found == {"a/sub/c.mkv"}
