"""Media index: tracked state of the library's videos and subtitles.

The :class:`~subtitle_tool.index.store.IndexStore` persists every discovered video
and subtitle to SQLite (``index.db``) and reconciles each scan against it, so
unchanged files are skipped, missing wanted languages are reported, and the library
can be browsed in the UI without re-walking the disk.
"""

from subtitle_tool.index.models import (
    HistoryEntry,
    IndexedSubtitle,
    IndexedVideo,
    LibraryVideo,
    ReconcileResult,
)
from subtitle_tool.index.store import IndexStore

__all__ = [
    "HistoryEntry",
    "IndexStore",
    "IndexedSubtitle",
    "IndexedVideo",
    "LibraryVideo",
    "ReconcileResult",
]
