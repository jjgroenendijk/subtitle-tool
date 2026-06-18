"""Readiness checks for the ``/health/ready`` probe.

Liveness only asks whether the process is up; readiness asks whether the local state
the tool needs to do real work is actually usable. That is: the config directory can
be read and written (the config file and both SQLite databases live there), and each
SQLite store answers a trivial query rather than merely existing as a handle. The
checks are deliberately cheap and read-only so the probe can be polled frequently.

Kept separate from the app factory so the logic is unit-testable without spinning up
the whole FastAPI application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


class _Pingable(Protocol):
    def ping(self) -> None: ...


@dataclass(frozen=True)
class ReadinessResult:
    """Outcome of the readiness checks: overall flag plus per-check detail."""

    ok: bool
    checks: dict[str, dict[str, object]]


def readiness(config_dir: Path, store: _Pingable, index: _Pingable) -> ReadinessResult:
    """Probe the dependencies needed to serve real work and report each one.

    Returns a :class:`ReadinessResult` whose ``ok`` is true only when every check
    passes; ``checks`` maps each dependency name to ``{"ok": bool, "detail": str}``
    so a failing probe response names exactly what is wrong.
    """
    checks = {
        "config_dir": _check_config_dir(config_dir),
        "job_store": _check_ping(store),
        "index_store": _check_ping(index),
    }
    ok = all(check["ok"] for check in checks.values())
    return ReadinessResult(ok=ok, checks=checks)


def _check_config_dir(config_dir: Path) -> dict[str, object]:
    if not config_dir.is_dir():
        return {"ok": False, "detail": f"config directory {config_dir} is not a directory"}
    if not os.access(config_dir, os.R_OK | os.W_OK):
        return {"ok": False, "detail": f"config directory {config_dir} is not readable/writable"}
    return {"ok": True, "detail": str(config_dir)}


def _check_ping(target: _Pingable) -> dict[str, object]:
    try:
        target.ping()
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "detail": "ok"}
