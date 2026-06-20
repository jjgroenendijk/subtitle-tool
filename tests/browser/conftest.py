"""Fixtures for the Playwright browser suite.

These tests drive the real web UI in Chromium against a live FastAPI server, so
they prove the browser behaviors a FastAPI ``TestClient`` cannot: Alpine
components, ``localStorage`` preferences, ``confirm()`` dialogs, ``EventSource``
wiring, and the absence of console/runtime errors during covered flows.

Everything is local and temporary: each server runs against a ``tmp_path`` config
directory and seeded media index, never the developer's real ``/config`` or media
library. The suite is marked ``browser`` (auto-applied here) so the existing
``uv run pytest`` / ``uv run pytest --cov`` runs deselect it via the
``-m "not browser"`` default in ``pyproject.toml``; CI runs it on its own with
``uv run pytest -m browser`` after installing Chromium.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from subtitle_tool.config import BootstrapSettings
from subtitle_tool.config.loader import save_config
from subtitle_tool.scanner import scan_paths
from subtitle_tool.web import create_app

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from fastapi import FastAPI
    from playwright.sync_api import Browser, BrowserContext, Page

    from subtitle_tool.config.models import Config

# Playwright is an optional dev tool; skip the whole suite cleanly when it (or its
# browser binary) is missing rather than erroring at import time.
pytest.importorskip("playwright.sync_api")

_HERE = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under ``tests/browser`` with the ``browser`` marker.

    Keeps the marker in one place instead of repeating ``pytestmark`` in each
    module, so the default ``-m "not browser"`` deselection stays reliable.
    """
    here = str(_HERE)
    for item in items:
        if here in str(item.path):
            item.add_marker("browser")


@dataclass
class LiveServer:
    """A running app server plus the temporary state it serves from."""

    base_url: str
    app: FastAPI
    config_dir: Path
    media_dir: Path

    def url(self, path: str = "/") -> str:
        return self.base_url + path


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def context(browser: Browser) -> Iterator[BrowserContext]:
    ctx = browser.new_context()
    try:
        yield ctx
    finally:
        ctx.close()


@pytest.fixture
def page(context: BrowserContext) -> Iterator[Page]:
    new_page = context.new_page()
    try:
        yield new_page
    finally:
        new_page.close()


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    """Collect console errors and uncaught page errors for the active page.

    Listeners are attached before any navigation in the test body, so a covered
    flow can assert the list stayed empty.
    """
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors


@pytest.fixture
def start_server(
    tmp_path: Path,
) -> Iterator[Callable[..., LiveServer]]:
    """Return a factory that starts a live app server for a given config.

    The factory seeds the media index from ``media_dir`` (when given) so the
    library view has rows to render, writes the config, then runs uvicorn in a
    background thread. Started servers are stopped on teardown.
    """
    import uvicorn

    servers: list[tuple[uvicorn.Server, threading.Thread]] = []

    def start(config: Config, *, media_dir: Path | None = None) -> LiveServer:
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        save_config(config, config_dir / "config.toml")

        app = create_app(
            BootstrapSettings(CONFIG_DIR=config_dir, BROWSE_ROOT=str(tmp_path)),
        )
        if media_dir is not None:
            app.state.index.reconcile(scan_paths([str(media_dir)], []))

        port = _free_port()
        settings = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            timeout_graceful_shutdown=1,
        )
        server = uvicorn.Server(settings)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        servers.append((server, thread))

        deadline = time.monotonic() + 10.0
        while not server.started:
            if time.monotonic() > deadline:
                raise AssertionError("uvicorn did not start in time")
            time.sleep(0.02)

        return LiveServer(
            base_url=f"http://127.0.0.1:{port}",
            app=app,
            config_dir=config_dir,
            media_dir=media_dir or tmp_path,
        )

    yield start

    for server, thread in servers:
        server.should_exit = True
        thread.join(timeout=10.0)
