"""Unit tests for the readiness checks behind ``/health/ready``."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.web.health import readiness


class FakeStore:
    """A store stand-in whose ping can be made to succeed or fail."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def ping(self) -> None:
        if self._error is not None:
            raise self._error


def test_ready_when_config_dir_and_stores_are_usable(tmp_path: Path) -> None:
    result = readiness(tmp_path, FakeStore(), FakeStore())

    assert result.ok is True
    assert all(check["ok"] for check in result.checks.values())


def test_not_ready_when_config_dir_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / "absent"

    result = readiness(missing, FakeStore(), FakeStore())

    assert result.ok is False
    assert result.checks["config_dir"]["ok"] is False
    # The other dependencies are still probed and reported.
    assert result.checks["job_store"]["ok"] is True


def test_not_ready_when_a_store_ping_fails(tmp_path: Path) -> None:
    result = readiness(tmp_path, FakeStore(error=RuntimeError("db gone")), FakeStore())

    assert result.ok is False
    assert result.checks["job_store"]["ok"] is False
    assert "db gone" in str(result.checks["job_store"]["detail"])
