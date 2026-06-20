"""Tests for directory walking, classification, and exclude patterns."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.scanner.walk import containing_roots, is_subtitle, is_video, iter_files


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


def test_trailing_slash_pattern_matches_directories_only(tmp_path: Path) -> None:
    # A trailing-slash gitignore marker matches a directory but not a like-named
    # file: the "cache" directory is pruned while a file named "cache" is kept.
    _touch(tmp_path / "show" / "cache")
    _touch(tmp_path / "cache" / "x.srt")

    found = {p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path, ["cache/"])}

    assert found == {"show/cache"}


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


def test_containing_roots_returns_every_containing_root(tmp_path: Path) -> None:
    media = tmp_path / "media"
    deep = media / "shows" / "Season 1"
    # Overlapping roots: every root that contains the path is returned, so the caller can
    # mirror a full scan's dedup rather than letting one root alone decide.
    assert containing_roots(deep, [media, media / "shows"]) == [media, media / "shows"]
    # No containing root: an empty list, so the caller falls back to the walk root.
    assert containing_roots(deep, [tmp_path / "other"]) == []
    # The path being a media root itself counts as contained.
    assert containing_roots(media, [media]) == [media]


def test_iter_files_honours_excludes_relative_to_exclude_root(tmp_path: Path) -> None:
    # A scoped scan re-roots at a changed directory deep inside the media tree. With the
    # media root as exclude_root, a root-relative pattern still matches the changed
    # directory's place in the tree, so its files are skipped.
    media = tmp_path / "media"
    excluded = media / "excluded" / "Season 1"
    _touch(excluded / "ep.mkv")

    found = list(iter_files(excluded, ["excluded/"], recursive=False, exclude_roots=[media]))

    assert found == []


def test_iter_files_yields_when_exclude_root_pattern_does_not_match(tmp_path: Path) -> None:
    # Same re-rooted walk, but the changed directory is not under an excluded tree, so
    # its files are yielded; the root-relative pattern is evaluated, just does not match.
    media = tmp_path / "media"
    wanted = media / "shows" / "Season 1"
    _touch(wanted / "ep.mkv")

    found = {
        p.relative_to(media).as_posix()
        for p in iter_files(wanted, ["excluded/"], recursive=False, exclude_roots=[media])
    }

    assert found == {"shows/Season 1/ep.mkv"}


def test_iter_files_keeps_file_any_overlapping_root_would_yield(tmp_path: Path) -> None:
    # Overlapping roots plus an anchored pattern: a full scan from /media still yields
    # shows/excluded/ep.mkv (the anchored /excluded/ only matches the top level), while
    # the /media/shows walk would prune it. The scoped scan must mirror that union and
    # keep the file, since at least one containing root does not exclude it.
    media = tmp_path / "media"
    changed = media / "shows" / "excluded"
    _touch(changed / "ep.mkv")

    found = {
        p.relative_to(media).as_posix()
        for p in iter_files(
            changed, ["/excluded/"], recursive=False, exclude_roots=[media, media / "shows"]
        )
    }

    assert found == {"shows/excluded/ep.mkv"}


def test_iter_files_skips_when_every_overlapping_root_excludes(tmp_path: Path) -> None:
    # The mirror case: an unanchored pattern excludes the directory under both roots, so
    # every containing root agrees and the scoped scan yields nothing.
    media = tmp_path / "media"
    changed = media / "shows" / "excluded"
    _touch(changed / "ep.mkv")

    found = list(
        iter_files(changed, ["excluded/"], recursive=False, exclude_roots=[media, media / "shows"])
    )

    assert found == []


def test_iter_files_does_not_descend_into_symlinked_directory(tmp_path: Path) -> None:
    # Symlinks are treated as plain entries: a symlinked directory is not followed, so
    # media reachable only through the link is not scanned. Real files beside it are.
    external = tmp_path / "external"
    _touch(external / "season" / "episode.mkv")
    library = tmp_path / "library"
    _touch(library / "real.mkv")
    (library / "linked").symlink_to(external, target_is_directory=True)

    found = {p.relative_to(library).as_posix() for p in iter_files(library, [])}

    assert found == {"real.mkv"}


def test_iter_files_yields_symlinked_file_like_a_normal_file(tmp_path: Path) -> None:
    # A symlink to a file is a leaf entry, not a directory, so it is yielded like any
    # other file rather than skipped.
    target = tmp_path / "store" / "movie.mkv"
    _touch(target)
    library = tmp_path / "library"
    library.mkdir()
    (library / "movie.mkv").symlink_to(target)

    found = {p.relative_to(library).as_posix() for p in iter_files(library, [])}

    assert found == {"movie.mkv"}
