"""Directory browsing for the media-path picker.

The config page's media-path picker lists a container directory's subdirectories
through ``/api/browse``. Browsing is confined to a configurable root so the picker only
ever offers paths the scanner can reach from inside the container, and any path
resolving outside that root is rejected.

The traversal and confinement logic lives here, separate from the app factory, so it is
unit-testable without the FastAPI app and so the browse route stays a thin wrapper. The
helper returns a :class:`BrowseResult` (body plus status code) the route serializes,
mirroring ``health.readiness``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowseResult:
    """Outcome of a browse request: the JSON body and the HTTP status code."""

    body: dict[str, object]
    status_code: int = 200


def browse(root: Path, path: str | None) -> BrowseResult:
    """List the subdirectories of ``path`` under ``root`` for the media-path picker.

    ``path`` defaults to ``root``. A target outside ``root`` is a 400, a non-directory
    a 404, and an unreadable directory a 400; otherwise a 200 with the directory's
    immediate subdirectories (hidden entries skipped, sorted case-insensitively) plus
    the parent and root for navigation.
    """
    root = root.resolve()
    target = Path(path).resolve() if path else root
    if target != root and root not in target.parents:
        return _error(f"path is outside the browsable root {root}", 400)
    if not target.is_dir():
        return _error(f"not a directory: {target}", 404)
    try:
        children = sorted(
            (
                child
                for child in target.iterdir()
                if not child.name.startswith(".") and child.is_dir()
            ),
            key=lambda child: child.name.lower(),
        )
    except OSError as exc:
        return _error(f"cannot read directory {target}: {exc}", 400)
    return BrowseResult(
        {
            "path": str(target),
            "parent": None if target == root else str(target.parent),
            "root": str(root),
            "entries": [{"name": child.name, "path": str(child)} for child in children],
        }
    )


def _error(message: str, status_code: int) -> BrowseResult:
    return BrowseResult({"error": message}, status_code)
