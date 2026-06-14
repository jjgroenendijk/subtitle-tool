"""Directory walking and file classification.

Walks media paths recursively, honouring gitignore-style exclude patterns, and
sorts the files found into videos and text subtitles by extension. Excluded
directories are pruned during the walk so their subtrees are never descended into.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path

# Container and subtitle extensions the tool cares about. Image-based subtitle
# formats (sub/idx, sup) are intentionally excluded: the tool only handles text
# subtitles.
VIDEO_EXTENSIONS = frozenset(
    {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mpg", ".mpeg", ".ts"}
)
SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".vtt"})


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_subtitle(path: Path) -> bool:
    return path.suffix.lower() in SUBTITLE_EXTENSIONS


def _translate(pattern: str) -> str:
    """Translate a gitignore-style pattern into an anchored regular expression.

    Implements the ``**`` semantics that ``fnmatch`` lacks: ``*`` and ``?`` never
    cross directory separators, a leading ``**/`` matches zero or more leading
    directories, and a trailing ``/**`` matches a directory together with its whole
    subtree (so the directory itself is matched and can be pruned).
    """
    i = 0
    n = len(pattern)
    out = ["^"]
    while i < n:
        if pattern[i:] == "/**":
            out.append("(?:/.*)?")
            break
        if pattern[i : i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "/":
            out.append("/")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return "".join(out)


@cache
def _compile(pattern: str) -> tuple[bool, re.Pattern[str]] | None:
    """Compile an exclude pattern, or return ``None`` for an empty one.

    The boolean reports whether the pattern is anchored to the scan root. A pattern
    containing a separator is matched against the full relative path; a pattern
    without one matches the basename at any depth, like gitignore. Trailing slashes
    (the gitignore directory marker) are ignored so ``Subs/`` and ``Subs`` behave
    the same.
    """
    cleaned = pattern.rstrip("/")
    if not cleaned:
        return None
    anchored = "/" in cleaned
    return anchored, re.compile(_translate(cleaned))


def _is_excluded(relative: Path, patterns: list[str]) -> bool:
    """Return whether ``relative`` (a path relative to a scan root) is excluded."""
    relative_posix = relative.as_posix()
    for pattern in patterns:
        compiled = _compile(pattern)
        if compiled is None:
            continue
        anchored, regex = compiled
        target = relative_posix if anchored else relative.name
        if regex.match(target):
            return True
    return False


def iter_files(root: Path, exclude_patterns: list[str]) -> Iterator[Path]:
    """Yield files under ``root`` that are not excluded, in deterministic order.

    Directories matching an exclude pattern are pruned, so their contents are never
    visited. Entries are sorted for a stable, reproducible scan order.
    """
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        directory = Path(dirpath)
        kept_dirs = []
        for name in sorted(dirnames):
            relative = (directory / name).relative_to(root)
            if not _is_excluded(relative, exclude_patterns):
                kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            relative = (directory / name).relative_to(root)
            if not _is_excluded(relative, exclude_patterns):
                yield directory / name
