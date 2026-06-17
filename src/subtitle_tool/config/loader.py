"""Loading, validating, and serializing the persisted config file.

The config file is TOML. ``tomllib`` (standard library, Python 3.11+) parses it;
``pydantic`` validates it. Both syntax and validation failures are surfaced as a
single :class:`ConfigError` with a message that names the offending fields, so an
invalid file is rejected with a clear explanation rather than a stack trace.
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import ValidationError

from subtitle_tool.config.models import Config


class ConfigError(Exception):
    """Raised when a config file cannot be read, parsed, or validated."""


def _format_validation_error(error: ValidationError) -> str:
    lines = []
    for err in error.errors():
        location = ".".join(str(part) for part in err["loc"]) or "(root)"
        lines.append(f"  {location}: {err['msg']}")
    return "invalid configuration:\n" + "\n".join(lines)


def load_config(path: str | Path) -> Config:
    """Load and validate the config file at ``path``.

    Raises :class:`ConfigError` if the file is missing, is not valid TOML, or fails
    validation.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from exc

    try:
        data: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from exc

    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc


def dump_config(config: Config) -> dict[str, Any]:
    """Return a plain, JSON/TOML-serializable dict for the given config."""
    return config.model_dump(mode="json")


def save_config(config: Config, path: str | Path) -> None:
    """Serialize ``config`` to TOML and write it atomically to ``path``.

    The file is written to a temporary sibling and renamed into place, so a reader
    (or a crash mid-write) never sees a half-written config. The parent directory is
    created if missing. Raises :class:`ConfigError` if the file cannot be written.
    """
    path = Path(path)
    text = tomli_w.dumps(dump_config(config))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise ConfigError(f"could not write config file {path}: {exc}") from exc
