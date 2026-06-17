"""SQLite-backed media index.

One small database (``index.db``) under ``/config`` records every video and
subtitle the tool has discovered. Each scan reconciles the filesystem against it:
a file whose fingerprint (size and mtime) matches its row is unchanged and skipped,
new or changed files are processed, and rows for files that have vanished are marked
gone. The index is authoritative for deciding what work a scan does, and it lets the
UI show the library and report missing wanted languages without re-walking the disk.

The index is never the safety mechanism: pipeline steps stay idempotent and writes
stay atomic, so a stale or rebuilt index can only cost a redundant no-op pass, never
a harmful action. Deleting ``index.db`` and running a full scan repopulates it.

Like :class:`~subtitle_tool.jobs.store.JobStore`, this is a single writer (the worker
thread) and reader (web request handlers), so one connection guarded by a lock is
enough; SQLite serializes the rest.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from subtitle_tool.index.models import (
    HistoryEntry,
    IndexedSubtitle,
    IndexedVideo,
    LibraryVideo,
    ReconcileResult,
)
from subtitle_tool.scanner.matching import split_subtitle_name
from subtitle_tool.scanner.models import ScanResult

_VIDEO_UPSERT = (
    "INSERT INTO videos (path, size, mtime, first_seen, last_seen, last_changed, gone) "
    "VALUES (?, ?, ?, ?, ?, ?, 0) "
    "ON CONFLICT(path) DO UPDATE SET size = excluded.size, mtime = excluded.mtime, "
    "last_seen = excluded.last_seen, last_changed = excluded.last_changed, gone = 0"
)

_SUBTITLE_UPSERT = (
    "INSERT INTO subtitles (path, size, mtime, language, flags, video_path, matched, "
    "first_seen, last_seen, last_changed, gone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0) "
    "ON CONFLICT(path) DO UPDATE SET size = excluded.size, mtime = excluded.mtime, "
    "language = excluded.language, flags = excluded.flags, "
    "video_path = excluded.video_path, matched = excluded.matched, "
    "last_seen = excluded.last_seen, last_changed = excluded.last_changed, gone = 0"
)

_HISTORY_INSERT = (
    "INSERT INTO subtitle_history (path, event, language, flags, at) VALUES (?, ?, ?, ?, ?)"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_changed TEXT NOT NULL,
    gone INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS subtitles (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    language TEXT,
    flags TEXT NOT NULL DEFAULT '',
    video_path TEXT,
    matched INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_changed TEXT NOT NULL,
    gone INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS subtitle_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    event TEXT NOT NULL,
    language TEXT,
    flags TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS subtitles_video_path ON subtitles(video_path);
CREATE INDEX IF NOT EXISTS subtitle_history_path ON subtitle_history(path);
"""


class IndexStore:
    """A SQLite media index, safe to share across threads."""

    def __init__(self, path: str | Path) -> None:
        self._lock = threading.Lock()
        path = Path(path)
        if path.parent != Path():
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def reset(self) -> None:
        """Clear every indexed row so the next scan reprocesses the whole library.

        Equivalent to deleting ``index.db``: with no rows, reconcile classifies every
        discovered file as new and the pipeline runs over all of them. Clearing the
        tables in place keeps the live connection (shared with the worker) valid rather
        than unlinking the file underneath it.
        """
        with self._lock:
            self._conn.executescript(
                "DELETE FROM subtitle_history; DELETE FROM subtitles; DELETE FROM videos;"
            )
            self._conn.commit()

    def ping(self) -> None:
        """Run a trivial query to confirm the index database is reachable.

        Used by the readiness probe. Raises ``sqlite3.Error`` if the connection is
        closed or the database file became unreadable.
        """
        with self._lock:
            self._conn.execute("SELECT 1").fetchone()

    def reconcile(
        self,
        scan_result: ScanResult,
        *,
        scope: frozenset[Path] | None = None,
        dry_run: bool = False,
        recursive: bool = True,
    ) -> ReconcileResult:
        """Reconcile a scan inventory against the index and return what changed.

        A file whose fingerprint matches its row is unchanged; new and changed files
        make up ``process_paths``. Files indexed within ``scope`` but absent from this
        inventory are marked gone (a ``None`` scope means a full scan, so every
        missing file is gone). ``dry_run`` computes the same classification without
        writing anything, so a dry run still skips unchanged files but never mutates
        the index.

        ``recursive`` must match the scan that produced ``scan_result``: a recursive
        scope covers a directory and its whole subtree, while a non-recursive scope
        (the watcher's) covers only files directly in the scoped directories, so files
        in unscanned subdirectories are never judged gone.

        Classification reads every existing row once into memory and writes the changes
        in batched ``executemany`` passes, so a large scan does not issue one query per
        discovered file.
        """
        videos = _inventory_videos(scan_result)
        subtitles = _inventory_subtitles(scan_result)
        result = ReconcileResult()
        now = datetime.now().astimezone().isoformat()

        with self._lock:
            existing_videos = {
                row["path"]: row for row in self._conn.execute("SELECT * FROM videos")
            }
            existing_subtitles = {
                row["path"]: row for row in self._conn.execute("SELECT * FROM subtitles")
            }
            seen_videos = {str(path) for path, _ in videos}
            seen_subtitles = {str(sub.path) for sub in subtitles}

            video_upserts: list[tuple] = []
            for path, (size, mtime) in videos:
                row = existing_videos.get(str(path))
                state = _classify(row, size, mtime)
                _bucket(result, path, state)
                video_upserts.append(_video_params(row, str(path), size, mtime, state, now))

            subtitle_upserts: list[tuple] = []
            history: list[tuple] = []
            for sub in subtitles:
                row = existing_subtitles.get(str(sub.path))
                state = _classify(row, sub.size, sub.mtime)
                _bucket(result, sub.path, state)
                params, event = _subtitle_params(row, sub, state, now)
                subtitle_upserts.append(params)
                if event is not None:
                    history.append(event)

            gone_paths, gone_videos, gone_subtitles, gone_history = _collect_gone(
                existing_videos,
                existing_subtitles,
                seen_videos,
                seen_subtitles,
                scope,
                now,
                recursive,
            )
            result.gone.update(gone_paths)

            if not dry_run:
                self._conn.executemany(_VIDEO_UPSERT, video_upserts)
                self._conn.executemany(_SUBTITLE_UPSERT, subtitle_upserts)
                if gone_videos:
                    self._conn.executemany("UPDATE videos SET gone = 1 WHERE path = ?", gone_videos)
                if gone_subtitles:
                    self._conn.executemany(
                        "UPDATE subtitles SET gone = 1 WHERE path = ?", gone_subtitles
                    )
                self._conn.executemany(_HISTORY_INSERT, history + gone_history)
                self._conn.commit()

        result.process_paths = result.new | result.changed
        return result

    def library(self, wanted_languages: list[str] | None = None) -> list[LibraryVideo]:
        """Return indexed videos with their subtitle coverage and missing languages.

        Gone rows are excluded. ``missing_languages`` lists the configured wanted
        languages that no present subtitle of a video provides.
        """
        wanted = wanted_languages or []
        with self._lock:
            video_rows = self._conn.execute(
                "SELECT * FROM videos WHERE gone = 0 ORDER BY path"
            ).fetchall()
            sub_rows = self._conn.execute(
                "SELECT * FROM subtitles WHERE gone = 0 AND video_path IS NOT NULL"
            ).fetchall()

        by_video: dict[str, list[IndexedSubtitle]] = {}
        for row in sub_rows:
            by_video.setdefault(row["video_path"], []).append(_subtitle_from_row(row))

        library: list[LibraryVideo] = []
        for row in video_rows:
            video = _video_from_row(row)
            subs = sorted(by_video.get(video.path, []), key=lambda s: s.path)
            present = {s.language for s in subs if s.language}
            missing = [code for code in wanted if code not in present]
            library.append(LibraryVideo(video=video, subtitles=subs, missing_languages=missing))
        return library

    def history(self, limit: int = 100) -> list[HistoryEntry]:
        """Return recent subtitle change history, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM subtitle_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            HistoryEntry(
                path=row["path"],
                event=row["event"],
                language=row["language"],
                flags=_split_flags(row["flags"]),
                at=datetime.fromisoformat(row["at"]),
            )
            for row in rows
        ]


# --- write parameter builders --------------------------------------------------


def _video_params(
    row: sqlite3.Row | None, path: str, size: int, mtime: int, state: str, now: str
) -> tuple:
    """Build the parameter tuple for a video upsert from its in-memory row (or None)."""
    first_seen = row["first_seen"] if row is not None else now
    last_changed = now if state != _UNCHANGED else row["last_changed"]
    return (path, size, mtime, first_seen, now, last_changed)


def _subtitle_params(
    row: sqlite3.Row | None, sub: _Subtitle, state: str, now: str
) -> tuple[tuple, tuple | None]:
    """Build a subtitle upsert tuple and the history event it records, if any."""
    first_seen = row["first_seen"] if row is not None else now
    last_changed = now if state != _UNCHANGED else row["last_changed"]
    flags = _join_flags(sub.flags)
    params = (
        str(sub.path),
        sub.size,
        sub.mtime,
        sub.language,
        flags,
        sub.video_path,
        int(sub.matched),
        first_seen,
        now,
        last_changed,
    )
    event: tuple | None = None
    if state == _NEW:
        event = (str(sub.path), "added", sub.language, flags, now)
    elif state == _CHANGED:
        event = (str(sub.path), "changed", sub.language, flags, now)
    return params, event


def _collect_gone(
    existing_videos: dict[str, sqlite3.Row],
    existing_subtitles: dict[str, sqlite3.Row],
    seen_videos: set[str],
    seen_subtitles: set[str],
    scope: frozenset[Path] | None,
    now: str,
    recursive: bool,
) -> tuple[set[Path], list[tuple], list[tuple], list[tuple]]:
    """Find indexed rows in scope but absent from this scan, for batched gone marking.

    Returns the gone paths plus the ``(path,)`` update tuples and history rows the
    write phase replays, so the caller never re-queries the index to mark files gone.
    """
    gone_paths: set[Path] = set()
    video_updates: list[tuple] = []
    subtitle_updates: list[tuple] = []
    history: list[tuple] = []
    for path, row in existing_videos.items():
        if row["gone"] or path in seen_videos or not _in_scope(path, scope, recursive):
            continue
        gone_paths.add(Path(path))
        video_updates.append((path,))
    for path, row in existing_subtitles.items():
        if row["gone"] or path in seen_subtitles or not _in_scope(path, scope, recursive):
            continue
        gone_paths.add(Path(path))
        subtitle_updates.append((path,))
        history.append((path, "gone", row["language"], row["flags"], now))
    return gone_paths, video_updates, subtitle_updates, history


# --- inventory helpers ---------------------------------------------------------

_NEW = "new"
_CHANGED = "changed"
_UNCHANGED = "unchanged"


class _Subtitle:
    """A subtitle drawn from the scan inventory with its fingerprint and metadata."""

    __slots__ = ("flags", "language", "matched", "mtime", "path", "size", "video_path")

    def __init__(
        self,
        path: Path,
        size: int,
        mtime: int,
        language: str | None,
        flags: list[str],
        video_path: str | None,
        matched: bool,
    ) -> None:
        self.path = path
        self.size = size
        self.mtime = mtime
        self.language = language
        self.flags = flags
        self.video_path = video_path
        self.matched = matched


def _inventory_videos(scan_result: ScanResult) -> list[tuple[Path, tuple[int, int]]]:
    videos: list[tuple[Path, tuple[int, int]]] = []
    for group in scan_result.video_groups:
        fingerprint = _fingerprint(group.video)
        if fingerprint is not None:
            videos.append((group.video, fingerprint))
    return videos


def _inventory_subtitles(scan_result: ScanResult) -> list[_Subtitle]:
    subtitles: list[_Subtitle] = []
    for group in scan_result.video_groups:
        for path in group.subtitles:
            sub = _build_subtitle(path, video_path=str(group.video), matched=True)
            if sub is not None:
                subtitles.append(sub)
    for standalone in scan_result.standalone_subtitles:
        sub = _build_subtitle(standalone.subtitle, video_path=None, matched=False)
        if sub is not None:
            subtitles.append(sub)
    return subtitles


def _build_subtitle(path: Path, *, video_path: str | None, matched: bool) -> _Subtitle | None:
    fingerprint = _fingerprint(path)
    if fingerprint is None:
        return None
    _base, language, flags = split_subtitle_name(path)
    size, mtime = fingerprint
    return _Subtitle(path, size, mtime, language, flags, video_path, matched)


def _fingerprint(path: Path) -> tuple[int, int] | None:
    """Return ``(size, mtime_ns)`` for ``path``, or ``None`` if it cannot be read."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _classify(row: sqlite3.Row | None, size: int, mtime: int) -> str:
    if row is None:
        return _NEW
    if row["gone"]:
        # A file that vanished and came back is treated as changed: re-process it and
        # refresh its fingerprint rather than trusting the stale pre-removal row.
        return _CHANGED
    if row["size"] == size and row["mtime"] == mtime:
        return _UNCHANGED
    return _CHANGED


def _bucket(result: ReconcileResult, path: Path, state: str) -> None:
    if state == _NEW:
        result.new.add(path)
    elif state == _CHANGED:
        result.changed.add(path)
    else:
        result.unchanged.add(path)


def _in_scope(path: str, scope: frozenset[Path] | None, recursive: bool) -> bool:
    """Whether ``path`` falls under one of the scanned ``scope`` roots.

    A ``None`` scope is a full scan: every indexed path is in scope, so any file the
    scan did not see is gone. A scoped (watcher) scan only walked some directories, so
    only files beneath those roots can be judged gone.

    With ``recursive=False`` the scope covers only files directly in the scoped
    directories, matching a non-recursive scan: a file in an unscanned subdirectory is
    out of scope and is never judged gone on the strength of a scan that never looked
    there.
    """
    if scope is None:
        return True
    candidate = Path(path)
    if recursive:
        return any(candidate == root or root in candidate.parents for root in scope)
    return candidate.parent in scope


def _join_flags(flags: list[str]) -> str:
    return ",".join(flags)


def _split_flags(flags: str) -> list[str]:
    return [flag for flag in flags.split(",") if flag]


def _video_from_row(row: sqlite3.Row) -> IndexedVideo:
    return IndexedVideo(
        path=row["path"],
        size=row["size"],
        mtime=row["mtime"],
        first_seen=datetime.fromisoformat(row["first_seen"]),
        last_seen=datetime.fromisoformat(row["last_seen"]),
        last_changed=datetime.fromisoformat(row["last_changed"]),
        gone=bool(row["gone"]),
    )


def _subtitle_from_row(row: sqlite3.Row) -> IndexedSubtitle:
    return IndexedSubtitle(
        path=row["path"],
        size=row["size"],
        mtime=row["mtime"],
        language=row["language"],
        flags=_split_flags(row["flags"]),
        video_path=row["video_path"],
        matched=bool(row["matched"]),
        first_seen=datetime.fromisoformat(row["first_seen"]),
        last_seen=datetime.fromisoformat(row["last_seen"]),
        last_changed=datetime.fromisoformat(row["last_changed"]),
        gone=bool(row["gone"]),
    )
