"""The single-job background worker.

A scan triggered from the UI must not block the request that started it, so the
worker runs the scan-and-pipeline pass on a background thread. Only one job runs at
a time (the architecture's one-job-per-container rule): :meth:`start` returns
``None`` if a job is already running. As the pipeline finishes each file the worker
records it in the store and publishes a live event through the broker; when the run
ends it writes the summary counts and prunes old history.

Milestone 6 wires this to the manual scan buttons only. The scheduler and watcher
(Milestone 7) will drive the same :meth:`start` method.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from subtitle_tool.config.models import Config
from subtitle_tool.jobs.broker import EventBroker
from subtitle_tool.jobs.models import JobFile, JobStatus
from subtitle_tool.jobs.store import JobStore
from subtitle_tool.pipeline import FileResult, run_pipeline
from subtitle_tool.scanner import scan


@dataclass
class _Counters:
    processed: int = 0
    changed: int = 0
    warnings: int = 0
    errors: int = 0


class Worker:
    """Runs scans on a background thread, one at a time, recording results."""

    def __init__(
        self,
        store: JobStore,
        broker: EventBroker,
        config_provider: Callable[[], Config],
    ) -> None:
        self._store = store
        self._broker = broker
        self._config_provider = config_provider
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, *, dry_run: bool) -> int | None:
        """Start a job and return its id, or ``None`` if one is already running."""
        mode = "dry-run" if dry_run else "real"
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return None
            job_id = self._store.create_job(mode)
            self._thread = threading.Thread(
                target=self._run,
                args=(job_id, dry_run, mode),
                name=f"job-{job_id}",
                daemon=True,
            )
            self._thread.start()
        return job_id

    def _run(self, job_id: int, dry_run: bool, mode: str) -> None:
        self._broker.publish({"event": "job_started", "job_id": job_id, "mode": mode})
        counters = _Counters()
        total = 0
        status = JobStatus.SUCCEEDED
        error: str | None = None
        try:
            config = self._config_provider()
            scan_result = scan(config)
            total = scan_result.subtitle_count

            def on_file(result: FileResult) -> None:
                self._handle_file(job_id, result, counters, total)

            run_pipeline(scan_result, config, dry_run=dry_run, on_file=on_file)
        except Exception as exc:  # noqa: BLE001 - a failed job is recorded, not raised
            status = JobStatus.FAILED
            error = str(exc)

        self._store.finish_job(
            job_id,
            status,
            total_files=total,
            changed_files=counters.changed,
            warning_count=counters.warnings,
            error_files=counters.errors,
            error=error,
        )
        self._store.prune(self._config_provider().history.retention_limit)
        self._broker.publish(
            {
                "event": "job_finished",
                "job_id": job_id,
                "status": status.value,
                "total": total,
                "changed": counters.changed,
                "warnings": counters.warnings,
                "errors": counters.errors,
                "error": error,
            }
        )
        with self._lock:
            self._thread = None

    def _handle_file(
        self, job_id: int, result: FileResult, counters: _Counters, total: int
    ) -> None:
        counters.processed += 1
        if result.error is not None:
            counters.errors += 1
        if result.changed:
            counters.changed += 1
        counters.warnings += len(result.warnings)

        file = _to_job_file(result)
        # Only files that did something or had something to say are worth storing.
        if file.changed or file.warnings or file.error is not None:
            self._store.add_file(job_id, file)

        self._broker.publish(
            {
                "event": "file_processed",
                "job_id": job_id,
                "processed": counters.processed,
                "total": total,
                "file": _file_event(file),
            }
        )


def _to_job_file(result: FileResult) -> JobFile:
    return JobFile(
        source=str(result.source),
        target=str(result.target),
        actions=[(action.type.value, action.description) for action in result.actions],
        warnings=list(result.warnings),
        error=result.error,
    )


def _file_event(file: JobFile) -> dict[str, Any]:
    return {
        "source": file.source,
        "target": file.target,
        "changed": file.changed,
        "actions": [list(action) for action in file.actions],
        "warnings": file.warnings,
        "error": file.error,
    }
