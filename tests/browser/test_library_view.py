"""Browser tests for the library view controls.

Cover the client-side quick filter, the column and full-path toggles, the
``localStorage``-backed view preferences persisting across a reload, the reset
action, and the server-side "show gaps only" navigation through the ``missing=1``
query parameter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_tool.config.models import Config

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from playwright.sync_api import Page

    from tests.browser.conftest import LiveServer

    StartServer = Callable[..., LiveServer]


def _wanted_config(media: Path, *wanted: str) -> Config:
    """A config scanning ``media`` with the given wanted languages filtered on."""
    return Config.model_validate(
        {
            "scan": {"media_paths": [str(media)]},
            "watcher": {"enabled": False},
            "language": {"filter": {"enabled": True, "wanted_languages": list(wanted)}},
        }
    )


def _build_library(media: Path) -> None:
    """Two videos: one with an English subtitle, one with none (a coverage gap)."""
    media.mkdir(parents=True, exist_ok=True)
    (media / "Alpha (2020).mkv").write_text("video", encoding="utf-8")
    (media / "Alpha (2020).en.srt").write_text(
        "1\n00:00:01,000 --> 00:00:04,000\nHello there.\n", encoding="utf-8"
    )
    (media / "Beta (2021).mkv").write_text("video", encoding="utf-8")


def test_quick_filter_hides_non_matching_rows(
    page: Page,
    console_errors: list[str],
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    _build_library(media)
    server = start_server(_wanted_config(media, "en"), media_dir=media)
    page.goto(server.url("/library"))

    rows = page.locator("#library tbody tr[data-name]")
    assert rows.count() == 2

    page.locator(".quick-filter").fill("alpha")
    # Wait on the settled outcome, not on a .filter-hidden element appearing:
    # before Alpine runs applyFilter() no row carries that class, and a
    # state="hidden" wait is satisfied by the missing selector, so it could
    # return before the Beta row is hidden. Assert exactly one row stays visible.
    page.wait_for_function(
        "() => [...document.querySelectorAll('#library tbody tr[data-name]')]"
        ".filter((row) => !row.classList.contains('filter-hidden')).length === 1",
    )
    visible = page.locator("#library tbody tr[data-name]:not(.filter-hidden)")
    assert visible.count() == 1
    assert "alpha" in visible.first.get_attribute("data-name")

    # A term matching nothing surfaces the empty-state notice.
    page.locator(".quick-filter").fill("nomatch")
    page.wait_for_selector(".quick-filter-empty:not([x-cloak])")
    assert console_errors == []


def test_column_and_path_toggles_update_table_state(
    page: Page,
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    _build_library(media)
    server = start_server(_wanted_config(media, "en"), media_dir=media)
    page.goto(server.url("/library"))

    table = page.locator("#library")
    page.locator(".column-picker summary").click()

    # Languages defaults visible; unchecking adds the hide-langs class.
    langs_toggle = page.locator('.col-toggle[value="langs"]')
    assert langs_toggle.is_checked()
    langs_toggle.uncheck()
    page.wait_for_function(
        "(el) => el.classList.contains('hide-langs')", arg=table.element_handle()
    )

    # Full paths defaults off; enabling adds the show-paths class.
    page.locator(".path-toggle").check()
    page.wait_for_function(
        "(el) => el.classList.contains('show-paths')", arg=table.element_handle()
    )


def test_view_preferences_persist_across_reload(
    page: Page,
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    _build_library(media)
    server = start_server(_wanted_config(media, "en"), media_dir=media)
    page.goto(server.url("/library"))

    page.locator(".column-picker summary").click()
    page.locator('.col-toggle[value="langs"]').uncheck()
    page.locator(".path-toggle").check()
    table = page.locator("#library")
    page.wait_for_function(
        "(el) => el.classList.contains('hide-langs') && el.classList.contains('show-paths')",
        arg=table.element_handle(),
    )

    page.reload()
    table = page.locator("#library")
    # The stored preferences are reapplied without any further interaction.
    page.wait_for_function(
        "(el) => el.classList.contains('hide-langs') && el.classList.contains('show-paths')",
        arg=table.element_handle(),
    )
    page.locator(".column-picker summary").click()
    assert not page.locator('.col-toggle[value="langs"]').is_checked()
    assert page.locator(".path-toggle").is_checked()


def test_reset_restores_default_view(
    page: Page,
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    _build_library(media)
    server = start_server(_wanted_config(media, "en"), media_dir=media)
    page.goto(server.url("/library"))

    page.locator(".column-picker summary").click()
    page.locator('.col-toggle[value="langs"]').uncheck()
    page.locator(".path-toggle").check()
    table = page.locator("#library")
    page.wait_for_function(
        "(el) => el.classList.contains('hide-langs')", arg=table.element_handle()
    )

    page.get_by_role("button", name="Reset view").click()
    page.wait_for_function(
        "(el) => !el.classList.contains('hide-langs') && !el.classList.contains('show-paths')",
        arg=table.element_handle(),
    )
    assert page.locator('.col-toggle[value="langs"]').is_checked()
    assert not page.locator(".path-toggle").is_checked()


def test_show_gaps_only_navigates_with_missing_param(
    page: Page,
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    _build_library(media)
    server = start_server(_wanted_config(media, "en"), media_dir=media)
    page.goto(server.url("/library"))

    assert page.locator("#library tbody tr[data-name]").count() == 2

    page.locator("#gaps-only").check()
    page.wait_for_url("**/library?**missing=1**")
    # Only the uncovered video remains after the server-side filter.
    rows = page.locator("#library tbody tr[data-name]")
    assert rows.count() == 1
    assert "beta" in rows.first.get_attribute("data-name")
