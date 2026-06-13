"""Interval scheduler that triggers unattended scans.

A single background thread sleeps for the configured interval, then submits a full
scan to the worker, and repeats. The interval is re-read from config on every cycle
so a change saved through the UI takes effect without a restart. An optional
scan-on-startup submits one run immediately when the scheduler starts.

The scheduler never runs a scan itself; it only submits :class:`ScanRequest`s to
the worker, which enforces the one-job-at-a-time rule and collapses overlapping
triggers. Submitting while a job runs simply queues a single follow-up.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from subtitle_tool.config.models import Config
from subtitle_tool.jobs import ScanRequest, Worker

_SECONDS_PER_HOUR = 3600.0


class Scheduler:
    """Submits a full scan to the worker on a configurable interval."""

    def __init__(self, worker: Worker, config_provider: Callable[[], Config]) -> None:
        self._worker = worker
        self._config_provider = config_provider
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the interval loop and, if configured, run one scan immediately."""
        if self._config_provider().scan.scan_on_startup:
            self._worker.submit(ScanRequest(trigger="startup"), queue_if_busy=True)
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the loop to exit and wait briefly for the thread to end."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _interval_seconds(self) -> float:
        return self._config_provider().scan.interval_hours * _SECONDS_PER_HOUR

    def _loop(self) -> None:
        while not self._stop.wait(self._interval_seconds()):
            self._worker.submit(ScanRequest(trigger="schedule"), queue_if_busy=True)
