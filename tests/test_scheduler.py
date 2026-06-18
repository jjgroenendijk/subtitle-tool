"""Tests for the interval scheduler that drives unattended scans."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from subtitle_tool.config.models import Config
from subtitle_tool.scheduler import Scheduler

if TYPE_CHECKING:
    from subtitle_tool.jobs import ScanRequest


class RecordingWorker:
    """A worker stand-in that records submitted requests instead of running them."""

    def __init__(self) -> None:
        self.requests: list[ScanRequest] = []

    def submit(self, request: ScanRequest, *, queue_if_busy: bool = True) -> int:
        self.requests.append(request)
        return len(self.requests)


def make_config(*, scan_on_startup: bool = False, interval_hours: float = 6.0) -> Config:
    return Config.model_validate(
        {"scan": {"scan_on_startup": scan_on_startup, "interval_hours": interval_hours}}
    )


def test_scan_on_startup_submits_one_run_immediately() -> None:
    worker = RecordingWorker()
    scheduler = Scheduler(worker, lambda: make_config(scan_on_startup=True))
    # Keep the loop from firing during the test by stretching the interval.
    scheduler._interval_seconds = lambda: 100.0

    scheduler.start()
    try:
        assert len(worker.requests) == 1
        assert worker.requests[0].trigger == "startup"
        assert worker.requests[0].scope is None
    finally:
        scheduler.stop()


def test_no_startup_scan_when_disabled() -> None:
    worker = RecordingWorker()
    scheduler = Scheduler(worker, lambda: make_config(scan_on_startup=False))
    scheduler._interval_seconds = lambda: 100.0

    scheduler.start()
    try:
        assert worker.requests == []
    finally:
        scheduler.stop()


def test_interval_loop_submits_scheduled_scans() -> None:
    worker = RecordingWorker()
    scheduler = Scheduler(worker, lambda: make_config(scan_on_startup=False))
    scheduler._interval_seconds = lambda: 0.02

    scheduler.start()
    try:
        deadline = time.monotonic() + 5.0
        while not worker.requests:
            if time.monotonic() > deadline:
                raise AssertionError("scheduler did not fire in time")
            time.sleep(0.01)
        assert worker.requests[0].trigger == "schedule"
        assert worker.requests[0].scope is None
    finally:
        scheduler.stop()


def test_stop_halts_the_loop() -> None:
    worker = RecordingWorker()
    scheduler = Scheduler(worker, lambda: make_config())
    scheduler._interval_seconds = lambda: 0.02

    scheduler.start()
    scheduler.stop()
    count_after_stop = len(worker.requests)
    time.sleep(0.1)

    # No further scans are submitted once stopped.
    assert len(worker.requests) == count_after_stop
