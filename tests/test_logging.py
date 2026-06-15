"""Tests for the structured JSON logging used for container log aggregation."""

from __future__ import annotations

import json
import logging
import sys

from subtitle_tool.logging import PACKAGE_LOGGER, StructuredFormatter, configure_logging


def _format(record: logging.LogRecord) -> dict[str, object]:
    return json.loads(StructuredFormatter().format(record))


def test_base_fields_are_present() -> None:
    record = logging.makeLogRecord(
        {"name": "subtitle_tool.jobs.worker", "msg": "job_started", "levelname": "INFO"}
    )
    payload = _format(record)

    assert payload["event"] == "job_started"
    assert payload["logger"] == "subtitle_tool.jobs.worker"
    assert payload["level"] == "INFO"
    assert "timestamp" in payload


def test_extra_fields_are_promoted_to_top_level_keys() -> None:
    record = logging.makeLogRecord(
        {"msg": "job_finished", "job_id": 7, "status": "succeeded", "elapsed_seconds": 1.5}
    )
    payload = _format(record)

    assert payload["job_id"] == 7
    assert payload["status"] == "succeeded"
    assert payload["elapsed_seconds"] == 1.5


def test_exception_info_is_flattened_into_error_detail() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "subtitle_tool", logging.ERROR, __file__, 1, "file_failed", None, sys.exc_info()
        )
    payload = _format(record)

    assert "ValueError: boom" in str(payload["error_detail"])


def test_output_is_one_json_object_per_line() -> None:
    record = logging.makeLogRecord({"msg": "subprocess_failed", "command": "ffmpeg"})
    line = StructuredFormatter().format(record)

    assert "\n" not in line
    assert json.loads(line)["command"] == "ffmpeg"


def test_configure_logging_is_idempotent() -> None:
    first = configure_logging()
    before = len(first.handlers)
    second = configure_logging()

    assert first is second
    assert len(second.handlers) == before
    assert first.name == PACKAGE_LOGGER
    assert first.propagate is False
