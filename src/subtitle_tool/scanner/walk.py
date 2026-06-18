"""Directory walking and file classification.

Walks media paths recursively, honouring gitignore-style exclude patterns, and
sorts the files found into videos and text subtitles by extension. Excluded
directories are pruned during the walk so their subtrees are never descended into.

Symlinked directories are followed (media libraries commonly link movies or
seasons from another volume) but the walk guards against loops and repeated work:
each directory's real identity (device + inode) is recorded the first time it is
kept, so a symlink back to an ancestor, or two links to the same tree, are pruned
rather than descended into again.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from pathspec import GitIgnoreSpec

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


def _real_dir_key(path: Path) -> tuple[int, int]:
    """Return a directory's real identity as a ``(device, inode)`` pair.

    ``Path.stat`` follows symlinks, so two paths that resolve to the same real
    directory (directly or via a symlink) share a key. The walk uses this to prune
    symlink loops and avoid traversing the same real tree more than once.
    """
    st = path.stat()
    return (st.st_dev, st.st_ino)


def iter_files(
    root: Path, exclude_patterns: list[str], *, recursive: bool = True
) -> Iterator[Path]:
    """Yield files under ``root`` that are not excluded, in deterministic order.

    Directories matching an exclude pattern are pruned, so their contents are never
    visited. Entries are sorted for a stable, reproducible scan order.

    With ``recursive=False`` only the files directly in ``root`` are yielded and no
    subdirectory is descended into. The watcher uses this to scan just the directory a
    file changed in without re-walking a large subtree, since matching is per-directory
    (external subtitles live beside their video) and nothing below ``root`` is relevant.

    Symlinked directories are followed. To keep a scan finite, each directory's real
    ``(device, inode)`` identity is recorded the first time it is kept; a directory
    that resolves to an already-seen real path (a loop back to an ancestor, or a
    second link to the same tree) is pruned. Directories that cannot be stat'd (for
    example a symlink that vanished mid-walk) are skipped.
    """
    root = Path(root)
    seen: set[tuple[int, int]] = set()
    try:
        seen.add(_real_dir_key(root))
    except OSError:
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        directory = Path(dirpath)
        if recursive:
            kept_dirs = []
            for name in sorted(dirnames):
                child = directory / name
                relative = child.relative_to(root)
                if _is_excluded(relative, exclude_patterns, is_dir=True):
                    continue
                try:
                    key = _real_dir_key(child)
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                kept_dirs.append(name)
            dirnames[:] = kept_dirs
        else:
            # Descend into nothing: os.walk yields ``root`` first, so clearing its
            # subdirectories here stops the walk after the top level.
            dirnames[:] = []
        for name in sorted(filenames):
            relative = (directory / name).relative_to(root)
            if not _is_excluded(relative, exclude_patterns):
                yield directory / name
