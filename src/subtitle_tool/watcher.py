"""Filesystem watcher that triggers scoped scans for new and changed files.

The watcher uses inotify (via ``watchdog``) on the configured media paths. Raw
events are never acted on directly: instead each changed file is fed to a stability
tracker, and only once a file's size and mtime have stayed put for the configured
window is its directory queued for a scan. That window is what keeps in-progress
copies and downloads from being touched mid-write. When files settle, the watcher
submits one scan to the worker scoped to just the changed directories, going through
the same scanner-and-pipeline flow as a full scan.

:class:`StabilityTracker` holds the debounce logic and is pure enough to test with a
fake clock; :class:`Watcher` wires it to a watchdog observer and a polling thread.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from subtitle_tool.config.models import Config
from subtitle_tool.jobs import ScanRequest, Worker


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
    """Feeds the path of every changed file to the tracker."""

    def __init__(self, note: Callable[[Path], None]) -> None:
        self._note = note

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # A move reports the destination as where the file now lives.
        raw = getattr(event, "dest_path", "") or event.src_path
        if raw:
            self._note(Path(os.fsdecode(raw)))


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
        paths = [Path(p) for p in config.scan.media_paths if Path(p).is_dir()]
        if not paths:
            return

        self._tracker = StabilityTracker(config.watcher.stability_window_seconds)
        handler = _EventHandler(self._tracker.note)
        self._observer = Observer()
        for path in paths:
            self._observer.schedule(handler, str(path), recursive=True)
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
        assert self._tracker is not None
        while not self._stop.wait(self._poll_interval):
            directories = self._tracker.poll()
            if directories:
                self._worker.submit(
                    ScanRequest(scope=frozenset(directories), trigger="watch"),
                    queue_if_busy=True,
                )
