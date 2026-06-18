"""The filesystem-safety layer shared by every pipeline step.

Two rules from ``docs/architecture.md`` live here:

- A rewrite never touches the target until a complete, validated replacement
  exists. The new content is written to a temporary file in the target's own
  directory (so the final step is an atomic same-filesystem rename), validated, and
  only then swapped in. A failure at any point leaves the original untouched and the
  temporary file removed.
- A write that would land on top of a different existing file appends a predictable
  numeric suffix instead of overwriting it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Container


class InvalidResult(Exception):
    """Raised by a validator when a pipeline result is not safe to write."""


def resolve_collision(target: Path, reserved: Container[Path] = frozenset()) -> Path:
    """Return ``target`` or, if it is taken, a suffixed sibling that is not.

    The suffix is appended before the extension (``name (1).srt``) so the result
    keeps the original extension and stays predictable across runs. A path counts as
    taken when it already exists on disk or appears in ``reserved``; the latter lets a
    caller planning several writes (such as a dry run) avoid handing out the same name
    twice before any file has been created.
    """

    def taken(path: Path) -> bool:
        return path.exists() or path in reserved

    if not taken(target):
        return target
    stem, suffix, parent = target.stem, target.suffix, target.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not taken(candidate):
            return candidate
        counter += 1


def safe_write(
    target: Path,
    text: str,
    *,
    validate: Callable[[Path], None],
    encoding: str = "utf-8",
) -> Path:
    """Atomically write ``text`` to ``target`` after ``validate`` accepts it.

    ``validate`` is called with the temporary file's path and must raise
    :class:`InvalidResult` if the result should not be committed. On any failure the
    temporary file is removed and the original ``target`` is left as it was.
    """
    target = Path(target)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        validate(tmp)
        tmp.replace(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target
