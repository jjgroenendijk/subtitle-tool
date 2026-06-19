"""Library view shaping: server-side sorting and pagination.

The library page lists indexed videos and sorts and paginates them server-side so the
order is stable across pages and needs no JavaScript. That ordering and slicing is
page logic, not app wiring, so it lives here as small pure helpers the route composes;
keeping it out of the app factory means library behavior can change without touching
lifecycle or route wiring. The helpers operate on the in-memory ``library()`` list of
``LibraryVideo`` records so counts stay correct across pages without re-querying.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from subtitle_tool.index.models import LibraryVideo

MAX_PER_PAGE = 200

# Sort keys the library table exposes, mapped to the value each pulls off a
# LibraryVideo. Anything else falls back to the default name sort.
_LIBRARY_SORTS = {
    "name": lambda v: v.video.path.rsplit("/", 1)[-1].lower(),
    "count": lambda v: len(v.subtitles),
    "missing": lambda v: len(v.missing_languages),
    "size": lambda v: v.video.size,
    "modified": lambda v: v.video.mtime,
}


def sort_library(videos: list[LibraryVideo], sort: str, direction: str) -> tuple[str, str]:
    """Sort ``videos`` in place by a validated column and direction.

    Returns the normalized ``(sort, direction)`` so the template highlights the
    column actually applied rather than a bad query value. Videos arrive ordered by
    path, so an unrecognized sort leaves that stable order intact.
    """
    sort = sort if sort in _LIBRARY_SORTS else "name"
    direction = direction if direction in ("asc", "desc") else "asc"
    videos.sort(key=_LIBRARY_SORTS[sort], reverse=(direction == "desc"))
    return sort, direction


def paginate(
    items: list[Any], page: int, per_page: int, *, missing: bool
) -> tuple[list[Any], dict[str, Any]]:
    """Slice ``items`` for the requested page, returning the slice and link metadata."""
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    pagination = {
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total": total,
        "missing": missing,
    }
    return items[start : start + per_page], pagination
