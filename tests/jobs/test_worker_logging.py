"""Worker tests for the structured runtime logs container operators rely on."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from subtitle_tool.jobs import worker as worker_module
from tests.helpers import build_library, make_worker, media_config, wait_for_worker

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def captured_logs() -> Iterator[list[logging.LogRecord]]:
    # Attach directly to the worker logger so capture does not depend on propagation,
    # which configure_logging disables on the package logger elsewhere in the suite.
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    worker_module.logger.addHandler(handler)
    previous_level = worker_module.logger.level
    worker_module.logger.setLevel(logging.INFO)
    try:
        yield records
    finally:
        worker_module.logger.removeHandler(handler)
        worker_module.logger.setLevel(previous_level)


def _event(records: list[logging.LogRecord], event: str) -> logging.LogRecord:
    return next(r for r in records if r.getMessage() == event)


def test_job_lifecycle_logs_carry_diagnostic_fields(
    tmp_path: Path, captured_logs: list[logging.LogRecord]
) -> None:
    media = tmp_path / "media"
    build_library(media, clean_srt=True)
    worker, _store, _broker = make_worker(tmp_path, media_config(media))

    job_id = worker.start(dry_run=True)
    assert job_id is not None
    wait_for_worker(worker)

    started = _event(captured_logs, "job_started")
    assert started.job_id == job_id
    assert started.trigger == "manual"
    assert started.mode == "dry-run"

    finished = _event(captured_logs, "job_finished")
    assert finished.job_id == job_id
    assert finished.status == "succeeded"
    assert finished.changed == 1
    assert isinstance(finished.elapsed_seconds, float)

    # The changed file is logged with its planned action types for diagnosis.
    changed = _event(captured_logs, "file_changed")
    assert changed.path.endswith("Movie (2020).fr.ass")
    assert "convert_format" in changed.actions
