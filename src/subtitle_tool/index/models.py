"""Records describing the media index and the result of reconciling a scan.

The index tracks every video and subtitle the tool has seen: its path (identity),
a fingerprint (size and mtime) used to decide whether it changed since the last
scan, the language and flags parsed from a subtitle's filename, the
subtitle-to-video match status, and first-seen / last-seen / last-changed
timestamps. These are plain read models the store returns and the web layer
renders.

:class:`ReconcileResult` is the outcome of reconciling a scan inventory against the
index: which files are new, changed, unchanged, or gone, and the set the pipeline
should process (new plus changed). Unchanged files are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class IndexedVideo:
    """A video row in the media index."""

    path: str
    size: int
    mtime: int
    first_seen: datetime
    last_seen: datetime
    last_changed: datetime
    gone: bool = False


@dataclass(frozen=True)
class IndexedSubtitle:
    """A subtitle row in the media index, with its parsed metadata and match status."""

    path: str
    size: int
    mtime: int
    language: str | None
    flags: list[str]
    video_path: str | None
    matched: bool
    first_seen: datetime
    last_seen: datetime
    last_changed: datetime
    gone: bool = False


@dataclass(frozen=True)
class LibraryVideo:
    """A video and its subtitle coverage, for the library view.

    ``missing_languages`` lists the configured wanted languages that no present
    subtitle provides, so coverage gaps are visible without re-walking the disk.
    """

    video: IndexedVideo
    subtitles: list[IndexedSubtitle]
    missing_languages: list[str]

    @property
    def languages(self) -> list[str]:
        """The distinct languages of the present subtitles, sorted, untagged last."""
        codes = sorted({s.language for s in self.subtitles if s.language})
        if any(s.language is None for s in self.subtitles):
            codes.append("und")
        return codes


@dataclass(frozen=True)
class HistoryEntry:
    """One recorded change to a subtitle, retained beyond per-job history."""

    path: str
    event: str
    language: str | None
    flags: list[str]
    at: datetime


@dataclass
class ReconcileResult:
    """What a scan-to-index reconciliation found.

    ``process_paths`` is the union of new and changed paths the pipeline should run;
    unchanged paths are skipped. The sets hold the same ``Path`` objects the scan
    inventory carried, so callers can filter that inventory directly.
    """

    process_paths: set[Path] = field(default_factory=set)
    new: set[Path] = field(default_factory=set)
    changed: set[Path] = field(default_factory=set)
    unchanged: set[Path] = field(default_factory=set)
    gone: set[Path] = field(default_factory=set)
