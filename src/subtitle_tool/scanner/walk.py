"""Directory walking and file classification.

Walks media paths recursively, honouring gitignore-style exclude patterns, and
sorts the files found into videos and text subtitles by extension. Excluded
directories are pruned during the walk so their subtrees are never descended into.

Symlinked directories are followed so media linked from another volume is scanned,
but each real directory is descended into at most once: the walk tracks the
``(st_dev, st_ino)`` identity of every directory it enters and prunes any child whose
real identity has already been seen, so a symlink loop cannot recurse forever and two
links to the same tree are not counted twice.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from pathspec import GitIgnoreSpec

from subtitle_tool.fs_identity import real_key

if TYPE_CHECKING:
    from collections.abc import Iterator

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


@cache
def _compile(patterns: tuple[str, ...]) -> GitIgnoreSpec:
    """Compile exclude patterns into a ``GitIgnoreSpec``.

    Matching is delegated to ``pathspec``'s gitignore implementation, which owns the
    wildmatch edge cases this module used to translate by hand: a pattern without a
    separator matches the basename at any depth, a pattern with one is matched
    against the full relative path, ``*`` and ``?`` never cross directory
    separators, ``**`` spans them, and a trailing slash marks a directory-only
    pattern. The compiled spec is cached per pattern set.
    """
    return GitIgnoreSpec.from_lines(patterns)


def _is_excluded(relative: Path, patterns: list[str], *, is_dir: bool = False) -> bool:
    """Return whether ``relative`` (a path relative to a scan root) is excluded.

    ``is_dir`` tells ``pathspec`` whether the target is a directory so directory-only
    patterns (a trailing-slash gitignore marker) match directories but not files.
    """
    spec = _compile(tuple(patterns))
    target = relative.as_posix()
    if is_dir:
        target += "/"
    return spec.match_file(target)


def iter_files(
    root: Path, exclude_patterns: list[str], *, recursive: bool = True
) -> Iterator[Path]:
    """Yield files under ``root`` that are not excluded, in deterministic order.

    Directories matching an exclude pattern are pruned, so their contents are never
    visited. Entries are sorted for a stable, reproducible scan order.

    Symlinked directories are followed, but each real directory is descended into only
    once: a child whose ``(st_dev, st_ino)`` identity has already been seen (a symlink
    loop, or a second link to an already-walked tree) is pruned, as is one that cannot
    be stat'd. Real directories are examined before symlink aliases, so when a directory
    and a symlink to it both sit in the same parent the real in-tree path claims the
    identity and the alias is pruned, not the reverse. Exclude patterns are checked
    first, against the path as seen from ``root``.

    With ``recursive=False`` only the files directly in ``root`` are yielded and no
    subdirectory is descended into. The watcher uses this to scan just the directory a
    file changed in without re-walking a large subtree, since matching is per-directory
    (external subtitles live beside their video) and nothing below ``root`` is relevant.
    """
    root = Path(root)
    seen: set[tuple[int, int]] = set()
    root_key = real_key(root)
    if root_key is not None:
        seen.add(root_key)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        directory = Path(dirpath)
        if recursive:
            kept_dirs = []
            # Claim identities for real directories before symlink aliases so a symlink
            # never hides a real in-tree path (which would churn the index by moving its
            # files under the alias). Descent order is restored to plain sorted order
            # afterwards for a stable, reproducible walk.
            for name in sorted(dirnames, key=lambda n: ((directory / n).is_symlink(), n)):
                relative = (directory / name).relative_to(root)
                if _is_excluded(relative, exclude_patterns, is_dir=True):
                    continue
                key = real_key(directory / name)
                if key is None or key in seen:
                    continue
                seen.add(key)
                kept_dirs.append(name)
            dirnames[:] = sorted(kept_dirs)
        else:
            # Descend into nothing: os.walk yields ``root`` first, so clearing its
            # subdirectories here stops the walk after the top level.
            dirnames[:] = []
        for name in sorted(filenames):
            relative = (directory / name).relative_to(root)
            if not _is_excluded(relative, exclude_patterns):
                yield directory / name
