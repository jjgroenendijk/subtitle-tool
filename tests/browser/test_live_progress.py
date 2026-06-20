"""Browser smoke test for the live job-progress UI.

Triggering a scan from the dashboard redirects to the job detail page, which must
surface a live running-job state (status, notice, progress bar, and stop control).
The worker is parked inside ``scan()`` so the running state is deterministic rather
than racing a fast job to completion; backend correctness is covered by the regular
pytest worker suite, so this only asserts the live UI appears.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import block_worker_scan, media_config

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest
    from playwright.sync_api import Page

    from tests.browser.conftest import LiveServer

    StartServer = Callable[..., LiveServer]


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
    # assert the live UI; the gate is released afterwards so the run can finish.
    entered, release = block_worker_scan(monkeypatch)
    server = start_server(media_config(media))

    page.goto(server.url("/"))
    page.get_by_role("button", name="Scan now (dry run)").click()

    # The scan trigger redirects to the new job's detail page.
    page.wait_for_url("**/jobs/**")
    entered.wait(5.0)

    # text_content() reads the raw DOM text; the status label is CSS-uppercased.
    status = page.locator("#job-status")
    assert status.text_content().strip() == "running"
    assert page.locator("#job-notice").text_content().startswith("[INFO] Scan started")
    assert page.locator("#live-progress").count() == 1
    assert page.locator("#job-stop").count() == 1

    # Release the worker and let the job finish: the job_finished SSE event flips the
    # live status in place (proving the EventSource wiring) and closes the stream, so
    # the server has no lingering subscriber at teardown.
    release.open()
    page.wait_for_function(
        "() => document.getElementById('job-status').textContent.trim().toLowerCase() "
        "!== 'running'",
        timeout=15000,
    )
