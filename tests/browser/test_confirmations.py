"""Browser tests for confirm-before-submit on destructive actions.

The config page's "Clear media index" maintenance form carries ``data-confirm``,
so ``app.js`` intercepts its submit with ``window.confirm``. Cancelling must leave
the page unchanged; accepting must submit the action and reach the success notice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import media_config

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from playwright.sync_api import Page

    from tests.browser.conftest import LiveServer

    StartServer = Callable[..., LiveServer]


def test_cancelling_destructive_submit_changes_nothing(
    page: Page,
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    server = start_server(media_config(tmp_path / "media"))
    page.goto(server.url("/config"))

    # Dismiss the confirm dialog: the form submit is prevented, so the page neither
    # navigates nor shows the index-cleared notice.
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Clear media index and force full reprocess").click()

    page.wait_for_timeout(200)
    assert page.url.rstrip("/").endswith("/config")
    assert page.locator(".notice.ok", has_text="Media index cleared").count() == 0


def test_accepting_destructive_submit_runs_the_action(
    page: Page,
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    server = start_server(media_config(tmp_path / "media"))
    page.goto(server.url("/config"))

    # Accept the confirm dialog: the form submits and the server redirects back with
    # the index-cleared confirmation.
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Clear media index and force full reprocess").click()

    page.wait_for_url("**/config?index_reset=1")
    assert page.locator(".notice.ok", has_text="Media index cleared").count() == 1
