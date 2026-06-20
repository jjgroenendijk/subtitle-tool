"""Browser tests for the configuration page Alpine components.

Cover the language picker (filtering and selected count) and the directory
picker (browsing ``/api/browse``, adding/removing paths, and keeping the
submitted textarea in sync), plus the standing requirement that the page loads
without console or runtime errors.
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


def test_config_page_loads_without_console_errors(
    page: Page,
    console_errors: list[str],
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    server = start_server(media_config(tmp_path / "media"))
    page.goto(server.url("/config"))
    page.wait_for_selector(".lang-picker")
    # Alpine has started: the cloaked count label is now revealed.
    page.wait_for_selector(".lang-count:not([x-cloak])", state="attached")
    assert console_errors == []


def test_language_picker_filters_and_counts(
    page: Page,
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    server = start_server(media_config(tmp_path / "media"))
    page.goto(server.url("/config"))

    picker = page.locator('.lang-picker[data-field="language.filter.wanted_languages"]')
    options = picker.locator(".lang-option")
    total = options.count()
    assert total > 1

    # Selecting a language updates the live count rendered by the component.
    english = picker.locator('.lang-option:has(input[value="en"])')
    english.locator("input").check()
    count = picker.locator(".lang-count")
    count.wait_for()
    assert count.inner_text().strip() == "1 selected"

    # Filtering hides non-matching options without touching the selection.
    picker.locator(".lang-filter").fill("english")
    page.wait_for_function(
        "(el) => Array.from(el.querySelectorAll('.lang-option'))"
        ".filter((o) => !o.hidden).length === 1",
        arg=picker.element_handle(),
    )
    assert english.locator("input").is_checked()

    # Clearing the filter restores every option.
    picker.locator(".lang-filter").fill("")
    page.wait_for_function(
        "(el) => Array.from(el.querySelectorAll('.lang-option')).every((o) => !o.hidden)",
        arg=picker.element_handle(),
    )


def test_directory_picker_browses_adds_and_removes(
    page: Page,
    start_server: StartServer,
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    (media / "Movies").mkdir(parents=True)
    (media / "Shows").mkdir(parents=True)
    server = start_server(media_config(media))
    page.goto(server.url("/config"))

    picker = page.locator(".dir-picker")
    textarea = picker.locator("textarea")
    # The picker seeds its state from the server-rendered media path.
    assert str(media) in textarea.input_value()

    # Open the browser at the browsable root and step down into the media tree.
    picker.get_by_role("button", name="Add directory").click()
    media_entry = picker.locator(".dir-entries button", has_text="media")
    media_entry.wait_for()
    media_entry.click()
    movies = picker.locator(".dir-entries button", has_text="Movies")
    movies.wait_for()
    movies.click()
    add_this = picker.get_by_role("button", name="Add this directory")
    add_this.wait_for()
    add_this.click()

    expected = str(media / "Movies")
    page.wait_for_function(
        "(arg) => arg.el.value.split('\\n').includes(arg.path)",
        arg={"el": textarea.element_handle(), "path": expected},
    )
    # The visible selected list reflects the added path.
    assert picker.locator(".path-list code", has_text=expected).count() == 1

    # Removing the original media path keeps the textarea the form submits in sync.
    remove = picker.locator(".path-list li", has_text=str(media)).first.get_by_role(
        "button", name="remove"
    )
    remove.click()
    page.wait_for_function(
        "(arg) => !arg.el.value.split('\\n').includes(arg.path)",
        arg={"el": textarea.element_handle(), "path": str(media)},
    )
    assert expected in textarea.input_value()
