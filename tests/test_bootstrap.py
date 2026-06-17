"""Tests for bootstrap settings read from the environment."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from subtitle_tool.config import BootstrapSettings, load_bootstrap

BOOTSTRAP_VARS = ["CONFIG_DIR", "PORT", "PUID", "PGID", "TZ"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in BOOTSTRAP_VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults_when_env_is_empty() -> None:
    settings = load_bootstrap()

    assert settings.config_dir == Path("/config")
    assert settings.port == 8000
    assert settings.puid == 1000
    assert settings.pgid == 1000
    assert settings.tz == "UTC"
    assert settings.config_file == Path("/config/config.toml")


def test_reads_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIG_DIR", "/data")
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("PUID", "1500")
    monkeypatch.setenv("PGID", "1600")
    monkeypatch.setenv("TZ", "Europe/Amsterdam")

    settings = load_bootstrap()

    assert settings.config_dir == Path("/data")
    assert settings.port == 9090
    assert settings.puid == 1500
    assert settings.pgid == 1600
    assert settings.tz == "Europe/Amsterdam"
    assert settings.config_file == Path("/data/config.toml")


def test_env_var_names_are_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("port", "7000")

    assert load_bootstrap().port == 7000


@pytest.mark.parametrize("port", ["0", "70000", "not-a-number"])
def test_invalid_port_is_rejected(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("PORT", port)

    with pytest.raises(ValidationError):
        BootstrapSettings()
