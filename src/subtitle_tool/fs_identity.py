"""Real directory identity used to follow symlinked trees exactly once.

A directory's real identity is its ``(st_dev, st_ino)`` pair, stat'd through any
symlinks. Walks that follow symlinks - the scanner walk and the watcher's watch-root
resolution - share this helper so two links to one tree resolve to a single identity and
a symlink loop is detectable as a repeat. It lives in a neutral module rather than under
``scanner/`` because more than one caller depends on it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def real_key(path: Path) -> tuple[int, int] | None:
    """Return a directory's real ``(st_dev, st_ino)`` identity, or ``None``.

    Stats through symlinks so two links to the same directory share one key. Returns
    ``None`` when the target cannot be stat'd (broken symlink, permission denied), which
    callers treat as "do not follow".
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_dev, stat.st_ino)
