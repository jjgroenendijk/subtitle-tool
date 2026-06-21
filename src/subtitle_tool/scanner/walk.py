"""Directory walking and file classification.

Walks media paths recursively, honouring gitignore-style exclude patterns, and
sorts the files found into videos and text subtitles by extension. Excluded
directories are pruned during the walk so their subtrees are never descended into.

Symlinks are treated as plain entries. A symlinked directory is not descended into
(``os.walk`` does not follow symlinks), and a symlinked file is yielded like any other
file. One caveat inherited from stock ``os.walk``: listing a directory classifies each
child with ``DirEntry.is_dir()``, which follows symlinks, so a symlinked child is stat'd
through to its target even though the walk will not descend it - a link to a slow or
offline volume costs that stat. Keep media on real in-tree paths; in a container, mount
each media volume directly rather than linking across them.

Like the standard ``os.walk`` it is built on, the walk does not track directory identity,
so a non-symlink mount cycle (a bind mount of an ancestor inside a media root) is not
guarded against and would recurse without end. Media roots are expected to be ordinary
directory trees without such cycles.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from pathspec import GitIgnoreSpec

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

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


def containing_roots(path: Path, media_roots: Iterable[Path]) -> list[Path]:
    """Return every media root that contains ``path`` (is ``path`` or an ancestor).

    Exclude patterns are gitignore-style and rooted at a media path, but a scoped
    watcher scan re-roots the walk at a changed directory deep inside that tree.
    Evaluating excludes relative to the changed directory would miss every
    root-relative pattern (``excluded/`` no longer sees the ``excluded`` segment
    above it), so the walk needs the media roots the directory belongs to as the bases
    for exclude matching.

    A full scan deduplicates overlapping roots, so a file is included as long as any
    root that contains it would yield it (one root excluding it does not remove a copy
    another root keeps). A scoped scan must mirror that: every containing root is
    returned so the caller can keep a file unless every one of them excludes it, rather
    than letting the most-specific root alone decide. Ancestry is purely lexical, so
    symlinks are not resolved and real in-tree paths compare as-is.
    """
    roots: list[Path] = []
    for candidate in media_roots:
        candidate = Path(candidate)
        if path == candidate or candidate in path.parents:
            roots.append(candidate)
    return roots


def iter_files(
    root: Path,
    exclude_patterns: list[str],
    *,
    recursive: bool = True,
    exclude_roots: Iterable[Path] | None = None,
) -> Iterator[Path]:
    """Yield files under ``root`` that are not excluded, in deterministic order.

    Directories matching an exclude pattern are pruned, so their contents are never
    visited. Entries are sorted for a stable, reproducible scan order.

    Symlinks are treated as plain entries: ``os.walk`` does not follow symlinked
    directories, so they are not descended into, while a symlinked file is yielded like
    any other file.

    Exclude patterns are checked against the path as seen from each base in
    ``exclude_roots`` when given, otherwise from ``root``. A scoped scan walks a changed
    directory deep inside a media tree but passes the media roots that contain it (see
    :func:`containing_roots`) so root-relative patterns still apply; each base must be
    ``root`` or an ancestor of it. An entry is excluded only when every base excludes it,
    mirroring how a full scan keeps a file any overlapping root would yield. When the
    walk root itself is excluded under every base the walk yields nothing.

    With ``recursive=False`` only the files directly in ``root`` are yielded and no
    subdirectory is descended into. The watcher uses this to scan just the directory a
    file changed in without re-walking a large subtree, since matching is per-directory
    (external subtitles live beside their video) and nothing below ``root`` is relevant.
    """
    root = Path(root)
    bases = [Path(base) for base in exclude_roots] if exclude_roots else [root]

    def excluded(absolute: Path, *, is_dir: bool) -> bool:
        # Excluded only when every base excludes it: a full scan would still yield the
        # file through any base that keeps it, and a scoped scan must match that.
        return all(
            _is_excluded(absolute.relative_to(base), exclude_patterns, is_dir=is_dir)
            for base in bases
        )

    # The walk re-roots at ``root``; ``os.walk`` only prunes its descendants, never the
    # root itself. When ``root`` sits inside a directory every base excludes (a scoped
    # scan of a changed directory under, say, ``excluded/``), nothing here should be
    # yielded. If ``root`` is itself one of the bases (a configured media root) a full
    # scan walks it directly, so it is never self-excluded regardless of ancestor bases.
    if root not in bases and all(
        _is_excluded(root.relative_to(base), exclude_patterns, is_dir=True) for base in bases
    ):
        return
    for dirpath, dirnames, filenames in os.walk(root):
        directory = Path(dirpath)
        if recursive:
            dirnames[:] = [
                name for name in sorted(dirnames) if not excluded(directory / name, is_dir=True)
            ]
        else:
            # Descend into nothing: os.walk yields ``root`` first, so clearing its
            # subdirectories here stops the walk after the top level.
            dirnames[:] = []
        for name in sorted(filenames):
            if not excluded(directory / name, is_dir=False):
                yield directory / name
