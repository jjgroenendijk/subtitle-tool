"""Browser smoke test for the live job-progress UI.

Triggering a scan and opening the job detail page must surface a live running-job
state (status, notice, progress bar, and stop control), and the job_finished SSE
event must flip that status in place. The worker is parked inside ``scan()`` so the
running state is deterministic rather than racing a fast job to completion; backend
correctness is covered by the regular pytest worker suite, so this only asserts the
live UI appears.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from tests.helpers import media_config

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest
    from playwright.sync_api import Page

    from tests.browser.conftest import LiveServer

    StartServer = Callable[..., LiveServer]


def _park_worker(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Event, threading.Event]:
    """Park the worker inside scan() until released, with no release timeout.

    Returns ``(entered, release)``: ``entered`` is set once the worker reaches
    scan(), and the worker blocks on ``release`` until the test sets it. Unlike
    the shared ``block_worker_scan`` helper, whose gate waits with a 5-second
    default, ``release`` is an unbounded Event: a slow Chromium cold start must
    never let the worker run (and publish job_finished into the void) before the
    page's EventSource has subscribed.
    """
    import subtitle_tool.jobs.worker as worker_module

    entered = threading.Event()
    release = threading.Event()
    real_scan = worker_module.scan

    def blocking_scan(cfg):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait()
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)
    return entered, release


def _wait_for_sse_subscriber(server: LiveServer, timeout: float = 5.0) -> None:
    """Block until the page's EventSource has registered with the event broker.

    The SSE stream only delivers events published after a subscriber's queue
    exists, so releasing the parked worker before the page has subscribed would
    let job_finished fire into the void and leave the status stuck at running.
    The broker's subscriber set is the authoritative "is anyone listening yet"
    signal; reading it from the test thread is a benign membership check.
    """
    broker = server.app.state.broker
    deadline = time.monotonic() + timeout
    while not broker._subscribers:
        if time.monotonic() > deadline:
            raise AssertionError("the job page's EventSource never subscribed")
        time.sleep(0.02)


def test_triggering_scan_surfaces_running_job(
    page: Page,
    start_server: StartServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "Movie (2020).mkv").write_text("video", encoding="utf-8")

    # Park the in-process worker inside scan() so the job stays running while we
    # assert the live UI; it is released only once the page has subscribed.
    entered, release = _park_worker(monkeypatch)
    server = start_server(media_config(media))

    # Trigger the scan through the worker rather than the dashboard button so the
    # job detail page is the only page that opens an EventSource: that keeps the
    # "has the page subscribed yet" wait below unambiguous, with no dashboard
    # subscriber lingering through the navigation.
    job_id = server.app.state.worker.start(dry_run=True)
    assert job_id is not None
    assert entered.wait(5.0)

    page.goto(server.url(f"/jobs/{job_id}"))

    # text_content() reads the raw DOM text; the status label is CSS-uppercased.
    status = page.locator("#job-status")
    assert status.text_content().strip() == "running"
    assert page.locator("#job-notice").text_content().startswith("[INFO] Scan started")
    assert page.locator("#live-progress").count() == 1
    assert page.locator("#job-stop").count() == 1

    # Only release once the page is actually listening, so the job_finished event
    # reaches its EventSource and flips the live status in place (proving the SSE
    # wiring) before the stream closes itself.
    _wait_for_sse_subscriber(server)
    release.set()
    page.wait_for_function(
        "() => document.getElementById('job-status').textContent.trim().toLowerCase() "
        "!== 'running'",
        timeout=15000,
    )
