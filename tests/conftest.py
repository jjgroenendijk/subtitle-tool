"""Shared pytest fixtures, currently the web app test client and its config dir."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from subtitle_tool.config import BootstrapSettings
from subtitle_tool.web import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


@pytest.fixture
def client(config_dir: Path) -> Iterator[TestClient]:
    app = create_app(BootstrapSettings(CONFIG_DIR=config_dir))
    # The context manager runs the lifespan, binding the broker's event loop.
    with TestClient(app) as test_client:
        yield test_client
