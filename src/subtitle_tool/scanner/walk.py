"""Directory walking and file classification.

Walks media paths recursively, honouring gitignore-style exclude patterns, and
sorts the files found into videos and text subtitles by extension. Excluded
directories are pruned during the walk so their subtrees are never descended into.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from fnmatch import fnmatch
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


def _is_excluded(relative: Path, patterns: list[str]) -> bool:
    """Return whether ``relative`` (a path relative to a scan root) is excluded.

    A pattern matches if it matches the basename, the full relative posix path, or
    any single path component. Trailing slashes (the gitignore directory marker) are
    ignored so ``Subs/`` and ``Subs`` behave the same.
    """
    relative_posix = relative.as_posix()
    for pattern in patterns:
        cleaned = pattern.rstrip("/")
        if not cleaned:
            continue
        if (
            fnmatch(relative.name, cleaned)
            or fnmatch(relative_posix, cleaned)
            or any(fnmatch(part, cleaned) for part in relative.parts)
        ):
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
