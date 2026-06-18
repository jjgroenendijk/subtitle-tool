"""Structured JSON logging to stdout for container log aggregation.

Runtime events (worker runs, per-file pipeline outcomes, subprocess failures) are
emitted as one JSON object per line so a container log collector can parse and index
them without a regex. Every module logs through ``logging.getLogger(__name__)``; this
module configures the package logger ``subtitle_tool`` once with a single stdout
handler and a formatter that promotes any structured fields passed via ``extra`` to
top-level JSON keys.

Use it as::

    import logging

    logger = logging.getLogger(__name__)
    logger.info("job_finished", extra={"job_id": 7, "status": "succeeded"})

which prints::

    {"timestamp": "...", "level": "INFO", "logger": "subtitle_tool.jobs.worker",
     "event": "job_finished", "job_id": 7, "status": "succeeded"}

The message is the machine-readable event name; the ``extra`` fields are the
structured context. Human-facing CLI output stays on ``print`` and is unaffected.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime

PACKAGE_LOGGER = "subtitle_tool"

# Attributes the standard library puts on every LogRecord. Anything else a caller
# attached via ``extra`` is a structured field we promote to a top-level JSON key.
_RESERVED_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
}

_configured = False


class StructuredFormatter(logging.Formatter):
    """Render a log record as a single JSON object, one per line.

    Base fields (timestamp, level, logger, event) are always present; any extra
    attributes the caller attached become top-level keys, and exception info is
    flattened into an ``error_detail`` string so a traceback survives aggregation.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["error_detail"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)

    # N802 (lowercase name) is ignored: this overrides logging.Formatter.formatTime,
    # whose camelCase name is fixed by the stdlib and cannot be renamed.
    def formatTime(self, record: logging.LogRecord, _datefmt: str | None = None) -> str:  # noqa: N802
        # ISO 8601 with the local offset, so timestamps are unambiguous in a log
        # collector regardless of the container timezone.
        return datetime.fromtimestamp(record.created).astimezone().isoformat()


def configure_logging(level: str | int | None = None) -> logging.Logger:
    """Configure the ``subtitle_tool`` package logger for structured stdout output.

    Idempotent: the first call installs the handler, later calls (the test suite
    builds many apps in one process) are no-ops so log lines are never duplicated.
    The level defaults to the ``LOG_LEVEL`` environment variable, then ``INFO``.
    """
    global _configured
    logger = logging.getLogger(PACKAGE_LOGGER)
    if _configured:
        return logger
    level = level or os.environ.get("LOG_LEVEL", "INFO")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    # The handler is the package's own; do not also bubble to the root logger and
    # risk a second, unformatted line from a default handler.
    logger.propagate = False
    _configured = True
    return logger
