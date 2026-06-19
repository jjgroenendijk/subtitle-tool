"""Filesystem watcher that triggers scoped scans for new and changed files.

The watcher uses inotify (via ``watchdog``) on the configured media paths. Raw
events are never acted on directly: instead each changed file is fed to a stability
tracker, and only once a file's size and mtime have stayed put for the configured
window is its directory queued for a scan. That window is what keeps in-progress
copies and downloads from being touched mid-write. When files settle, the watcher
submits one scan to the worker scoped to just the changed directories, going through
the same scanner-and-pipeline flow as a full scan.

Because watchdog's recursive inotify watches do not descend into symlinked
subdirectories on Linux, watching the media roots alone would miss changes inside the
symlinked trees the scanner walk now follows (issue #107). :func:`resolve_watch_roots`
resolves those trees with the same ``(st_dev, st_ino)`` identity guard the scanner uses
and returns the extra in-tree paths to watch, each real tree once.

:class:`StabilityTracker` holds the debounce logic and is pure enough to test with a
fake clock; :class:`Watcher` wires it to a watchdog observer and a polling thread.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import (
    EVENT_TYPE_CREATED,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_MOVED,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from subtitle_tool.fs_identity import real_key
from subtitle_tool.jobs import ScanRequest, Worker

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from subtitle_tool.config.models import Config


@dataclass
class _Sample:
    size: int
    mtime: float
    stable_since: float


class StabilityTracker:
    """Tracks changed files and reports directories whose files have settled.

    A file becomes ready only after a poll observes its size and mtime unchanged for
    at least ``window_seconds`` since they last changed. Files that vanish (a rename
    away, a deleted temp) are dropped silently. ``clock`` and ``stat`` are injectable
    so the debounce can be tested deterministically.
    """

    def __init__(
        self,
        window_seconds: float,
        *,
        clock: Callable[[], float] | None = None,
        stat: Callable[[Path], os.stat_result] = os.stat,
    ) -> None:
        self._window = window_seconds
        self._clock = clock or time.monotonic
        self._stat = stat
        self._lock = threading.Lock()
        self._pending: dict[Path, _Sample | None] = {}

    def note(self, path: Path) -> None:
        """Register a changed file to be checked on the next poll."""
        with self._lock:
            # A fresh note resets nothing already in flight; the poll re-stats and
            # decides. Setting to None only when unseen avoids losing the prior sample.
            self._pending.setdefault(path, None)

    def poll(self) -> set[Path]:
        """Re-stat tracked files; return directories of any that have settled."""
        ready: set[Path] = set()
        with self._lock:
            for path in list(self._pending):
                try:
                    info = self._stat(path)
                except OSError:
                    # Gone or unreadable: stop tracking it.
                    del self._pending[path]
                    continue
                now = self._clock()
                sample = self._pending[path]
                if sample is None or sample.size != info.st_size or sample.mtime != info.st_mtime:
                    self._pending[path] = _Sample(info.st_size, info.st_mtime, now)
                elif now - sample.stable_since >= self._window:
                    ready.add(path.parent)
                    del self._pending[path]
        return ready

    @property
    def tracked_count(self) -> int:
        with self._lock:
            return len(self._pending)


class _EventHandler(FileSystemEventHandler):
    """Feeds the path of files mutated by create/modify/move events to the tracker.

    Only mutation events that can make a file need processing are acted on. Reading
    files during a scan emits open/access/close events, and acting on those would let
    a scan trigger another scan in a feedback loop (see issue #27); those event types
    are ignored. Deletions are ignored too: a vanished file has nothing to process.

    ``rewrite`` maps the real path watchdog reports back to the in-tree path a full scan
    would use. It matters only for symlinked trees, which inotify can watch only by their
    real target: rewriting keeps the queued scope consistent with the scanner walk so the
    index does not churn. It defaults to the identity for plain media roots.
    """

    _MUTATION_EVENTS = frozenset({EVENT_TYPE_CREATED, EVENT_TYPE_MODIFIED, EVENT_TYPE_MOVED})

    def __init__(
        self, note: Callable[[Path], None], *, rewrite: Callable[[Path], Path] | None = None
    ) -> None:
        self._note = note
        self._rewrite = rewrite or (lambda path: path)

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in self._MUTATION_EVENTS:
            return
        # A move reports the destination as where the file now lives.
        raw = getattr(event, "dest_path", "") or event.src_path
        if raw:
            self._note(self._rewrite(Path(os.fsdecode(raw))))


@dataclass(frozen=True)
class WatchRoot:
    """One recursive inotify watch and how to read its events.

    ``observe`` is the real path the watch is scheduled on; inotify watches inodes, so a
    symlinked tree can only be watched by its resolved target. ``report`` is the in-tree
    path a full scan would use for the same files. Events arrive under ``observe`` and are
    rewritten to ``report`` so a watch-triggered scoped scan and a full scan agree on the
    directory and the index does not churn. For a plain media root the two are equal.
    """

    observe: Path
    report: Path


def _collect_symlink_targets(base: Path, covered: set[tuple[int, int]]) -> list[Path]:
    """Mark the real subtree of ``base`` covered; return symlinked dirs to watch too.

    Walks ``base`` *without* following symlinks, so it stays inside exactly the subtree a
    recursive inotify watch on ``base`` already covers, and marks every real directory it
    reaches in ``covered``. Each symlinked child directory is returned (as an in-tree path
    under ``base``) so the caller can decide whether to schedule a separate watch on it:
    returning rather than deciding here lets the caller compare against the full ``covered``
    set once this walk has finished, so a real in-tree path that the same walk also reaches
    always wins over an alias to it.
    """
    targets: list[Path] = []
    for dirpath, dirnames, _ in os.walk(base, followlinks=False):
        directory = Path(dirpath)
        key = real_key(directory)
        if key is not None:
            covered.add(key)
        dirnames[:] = sorted(dirnames)
        for name in dirnames:
            child = directory / name
            if child.is_symlink():
                # os.walk(followlinks=False) will not descend into this; a recursive
                # inotify watch will not either, so it needs its own watch.
                targets.append(child)
    return targets


def resolve_watch_roots(media_paths: Iterable[Path]) -> list[WatchRoot]:
    """Resolve the recursive inotify watches to schedule for the media paths.

    On Linux, watchdog's recursive inotify watches do not descend into symlinked
    subdirectories, so a watch on a media root alone misses changes inside any symlinked
    directory tree beneath it - exactly the trees the scanner walk now follows (issue
    #107). This returns one :class:`WatchRoot` per media root plus one for every symlinked
    directory tree reachable beneath them, each real tree only once, resolved with the same
    ``(st_dev, st_ino)`` identity guard the scanner uses.

    Each watch is observed at its resolved real path (inotify watches inodes, and a watch
    scheduled on a symlink path receives nothing) but reports the in-tree path a full scan
    walks, so a watch-triggered scoped scan and a full scan agree on the directory and the
    index does not churn between them. Symlink loops and trees reachable through more than
    one link resolve to an already-seen identity and are skipped, and an alias to a real
    directory that is itself in-tree defers to that real path, which the recursive watch
    already covers.
    """
    covered: set[tuple[int, int]] = set()
    queued: set[tuple[int, int]] = set()
    roots: list[WatchRoot] = []
    queue: deque[Path] = deque(p for p in media_paths if p.is_dir())
    while queue:
        report = queue.popleft()
        key = real_key(report)
        if key is None or key in covered:
            continue
        roots.append(WatchRoot(observe=Path(os.path.realpath(report)), report=report))
        # Mark base's real subtree covered first, then queue only those symlink targets
        # still uncovered, so an alias to an in-tree real path defers to the real path.
        for target in _collect_symlink_targets(report, covered):
            target_key = real_key(target)
            if target_key is None or target_key in covered or target_key in queued:
                continue
            queued.add(target_key)
            queue.append(target)
    return roots


def _make_event_rewriter(roots: list[WatchRoot]) -> Callable[[Path], Path]:
    """Build the function mapping a real event path back to its in-tree path.

    Matches the longest observed prefix so nested watches resolve to the closest one, then
    re-roots the path under that watch's ``report`` path. A path under no watch (which
    should not happen) is returned unchanged.
    """
    prefixes = sorted(
        ((str(root.observe), root.report) for root in roots),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )

    def rewrite(path: Path) -> Path:
        text = str(path)
        for observe, report in prefixes:
            if text == observe:
                return report
            if text.startswith(observe + os.sep):
                return report / text[len(observe) + 1 :]
        return path

    return rewrite


class Watcher:
    """Watches media paths and submits scoped scans once files settle."""

    def __init__(
        self,
        worker: Worker,
        config_provider: Callable[[], Config],
        *,
        poll_interval: float = 1.0,
    ) -> None:
        self._worker = worker
        self._config_provider = config_provider
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._observer: Any = None  # watchdog observer, set on start
        self._tracker: StabilityTracker | None = None

    def start(self) -> None:
        """Begin watching, unless disabled or no media path exists to watch."""
        config = self._config_provider()
        if not config.watcher.enabled:
            return
        # Watch the media roots plus the real target of every symlinked tree beneath them:
        # watchdog's recursive inotify watches do not descend into symlinked directories,
        # so the roots alone would miss changes in trees the scanner walk follows (#107).
        roots = resolve_watch_roots(Path(p) for p in config.scan.media_paths)
        if not roots:
            return

        self._tracker = StabilityTracker(config.watcher.stability_window_seconds)
        handler = _EventHandler(self._tracker.note, rewrite=_make_event_rewriter(roots))
        self._observer = Observer()
        for root in roots:
            self._observer.schedule(handler, str(root.observe), recursive=True)
        self._observer.start()

        self._thread = threading.Thread(target=self._poll_loop, name="watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the observer and polling thread."""
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _poll_loop(self) -> None:
        assert self._tracker is not None  # noqa: S101  # internal invariant: set in start()
        while not self._stop.wait(self._poll_interval):
            directories = self._tracker.poll()
            if directories:
                self._worker.submit(
                    ScanRequest(scope=frozenset(directories), trigger="watch"),
                    queue_if_busy=True,
                )
