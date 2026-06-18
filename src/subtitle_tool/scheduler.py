"""Interval scheduler that triggers unattended scans.

A background thread submits a full scan to the worker every interval, with an optional
scan-on-startup. The interval is re-read from config each cycle so a UI change takes
effect without a restart. The worker, not the scheduler, enforces one-job-at-a-time.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from subtitle_tool.jobs import ScanRequest, Worker

if TYPE_CHECKING:
    from collections.abc import Callable

    from subtitle_tool.config.models import Config

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
