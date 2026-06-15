"""The single-job background worker.

A scan triggered from the UI, the scheduler, or the watcher must not block the
caller, so the worker runs the scan-and-pipeline pass on a background thread. Only
one job runs at a time (the architecture's one-job-per-container rule). The thread
stays alive across queued follow-ups: a trigger that arrives while a job runs does
not start a second job and is not dropped, it is collapsed into a single pending
request that runs once the current job finishes. Watcher scopes merge into that
pending request, so a burst of file events becomes one scoped follow-up scan.

As the pipeline finishes each file the worker records it in the store and publishes
a live event through the broker; when a run ends it writes the summary counts and
prunes old history.

Manual scans (:meth:`start`) keep the simpler "rejected while busy" contract the UI
expects; automated triggers use :meth:`submit` with ``queue_if_busy=True``.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from subtitle_tool.config.models import Config, HistoryConfig
from subtitle_tool.jobs.broker import EventBroker
from subtitle_tool.jobs.models import JobFile, JobStatus
from subtitle_tool.jobs.store import JobStore
from subtitle_tool.pipeline import FileResult, PipelineCancelled, run_pipeline
from subtitle_tool.scanner import scan, scan_paths
from subtitle_tool.scanner.models import ScanResult

if TYPE_CHECKING:
    from subtitle_tool.index import IndexStore


# Fallback retention used when the config cannot be loaded, so a failed job is still
# pruned with the model's default rather than crashing the worker thread.
_DEFAULT_RETENTION_LIMIT: int = HistoryConfig.model_fields["retention_limit"].default


@dataclass(frozen=True)
class ScanRequest:
    """One request for a scan-and-pipeline run.

    ``scope`` is ``None`` for a full scan of every configured media path, or a set
    of directories for a watcher-triggered scan limited to where files changed.
    ``trigger`` labels the source (``manual``, ``startup``, ``schedule``, ``watch``)
    for logging and event payloads.
    """

    dry_run: bool = False
    scope: frozenset[Path] | None = None
    trigger: str = "manual"

    @property
    def mode(self) -> str:
        return "dry-run" if self.dry_run else "real"


def merge_requests(existing: ScanRequest | None, incoming: ScanRequest) -> ScanRequest:
    """Collapse two pending requests into one.

    A full scan (``scope is None``) subsumes any scoped scan; otherwise scopes
    union. A real run dominates a dry run so queued real work is never silently
    downgraded. The incoming trigger label wins as the more recent cause.
    """
    if existing is None:
        return incoming
    if existing.scope is None or incoming.scope is None:
        scope: frozenset[Path] | None = None
    else:
        scope = existing.scope | incoming.scope
    return ScanRequest(
        dry_run=existing.dry_run and incoming.dry_run,
        scope=scope,
        trigger=incoming.trigger,
    )


@dataclass
class _Counters:
    processed: int = 0
    changed: int = 0
    warnings: int = 0
    errors: int = 0
    # The advertised work total. Seeded from the inventory before the run, then
    # raised so it never trails ``processed``: the video phase and the subtitles it
    # extracts are work discovered during the run, not in the pre-run inventory, so a
    # fixed total would let progress report more processed files than the total.
    total: int = 0


class Worker:
    """Runs scans on a background thread, one at a time, recording results."""

    def __init__(
        self,
        store: JobStore,
        broker: EventBroker,
        config_provider: Callable[[], Config],
        index: IndexStore | None = None,
    ) -> None:
        self._store = store
        self._broker = broker
        self._config_provider = config_provider
        self._index = index
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pending: ScanRequest | None = None
        # Set to request the running job stop at its next file boundary; cleared at
        # the start of every job so a stale request never cancels a fresh run.
        self._cancel = threading.Event()
        self._current_job_id: int | None = None

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def current_job_id(self) -> int | None:
        """Id of the job running right now, or ``None`` when the worker is idle."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._current_job_id
            return None

    def cancel(self, job_id: int | None = None) -> bool:
        """Request the active job stop cooperatively; return whether one was signalled.

        Stopping is the user's deliberate choice, so any queued follow-up is dropped:
        the worker goes idle once the current job unwinds rather than starting the
        collapsed pending run. ``job_id``, when given, only cancels if it matches the
        job actually running, so a stale Stop click for a finished job is a no-op.
        The stop is observed at the next file boundary in the pipeline; the current
        file finishes its atomic write first.
        """
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            if not running or self._current_job_id is None:
                return False
            if job_id is not None and job_id != self._current_job_id:
                return False
            self._pending = None
            self._cancel.set()
            return True

    def start(self, *, dry_run: bool) -> int | None:
        """Start a manual job and return its id, or ``None`` if one is running.

        Manual scans are not queued: a user clicking scan while a job runs is told
        the worker is busy rather than silently lining up a second run.
        """
        return self.submit(ScanRequest(dry_run=dry_run, trigger="manual"), queue_if_busy=False)

    def submit(self, request: ScanRequest, *, queue_if_busy: bool = True) -> int | None:
        """Run ``request`` now, or collapse it into the pending follow-up if busy.

        Returns the new job id when a run starts immediately, or ``None`` when the
        request was queued (or rejected, for ``queue_if_busy=False``).
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if queue_if_busy:
                    self._pending = merge_requests(self._pending, request)
                return None
            job_id = self._store.create_job(request.mode)
            self._thread = threading.Thread(
                target=self._run,
                args=(job_id, request),
                name=f"job-{job_id}",
                daemon=True,
            )
            self._thread.start()
            return job_id

    def _run(self, job_id: int, request: ScanRequest) -> None:
        """Run the given job, then drain any follow-up that queued while it ran."""
        self._run_one(job_id, request)
        while True:
            with self._lock:
                pending = self._pending
                self._pending = None
                if pending is None:
                    self._thread = None
                    self._current_job_id = None
                    return
                job_id = self._store.create_job(pending.mode)
            self._run_one(job_id, pending)

    def _run_one(self, job_id: int, request: ScanRequest) -> None:
        with self._lock:
            self._current_job_id = job_id
            self._cancel.clear()
        self._broker.publish(
            {
                "event": "job_started",
                "job_id": job_id,
                "mode": request.mode,
                "trigger": request.trigger,
            }
        )
        counters = _Counters()
        status = JobStatus.SUCCEEDED
        error: str | None = None
        config: Config | None = None
        # Captured once config loads so retention pruning runs even when the job
        # body fails; a config load failure leaves the safe default in place.
        retention_limit = _DEFAULT_RETENTION_LIMIT
        # Parent directories of files the pipeline changed, re-reconciled after the run
        # so the index reflects renames, deletes, rewrites, and extracted subtitles.
        touched: set[Path] = set()
        try:
            config = self._config_provider()
            retention_limit = config.history.retention_limit
            scan_result = self._scan(config, request)
            # Reconcile against the media index: unchanged files are skipped, so a
            # rescan of a clean library does no work. Without an index every file is
            # processed.
            process_paths = self._reconcile(scan_result, request)
            counters.total = _count_to_process(scan_result, process_paths)

            def on_file(result: FileResult) -> None:
                self._handle_file(job_id, result, counters, dry_run=request.dry_run)
                if not request.dry_run and result.changed:
                    touched.add(result.source.parent)
                    touched.add(result.target.parent)

            run_pipeline(
                scan_result,
                config,
                dry_run=request.dry_run,
                on_file=on_file,
                process_paths=process_paths,
                should_cancel=self._cancel.is_set,
            )
        except PipelineCancelled:
            # A user stop, observed at a file boundary: the files already processed
            # are recorded, the rest are left for the next scan (steps are idempotent).
            status = JobStatus.CANCELLED
        except Exception as exc:  # noqa: BLE001 - a failed job is recorded, not raised
            status = JobStatus.FAILED
            error = str(exc)

        # A real run can rename, delete, rewrite, or extract files after the pre-pipeline
        # reconcile, leaving the index describing the old state. Re-reconcile the touched
        # directories so the index reflects the final filesystem, scoped so files outside
        # them are never judged gone. Cancelled and failed runs still refresh what they
        # managed to change.
        if config is not None and not request.dry_run:
            self._refresh_index(config, touched)

        self._store.finish_job(
            job_id,
            status,
            total_files=counters.total,
            changed_files=counters.changed,
            warning_count=counters.warnings,
            error_files=counters.errors,
            error=error,
        )
        self._prune(retention_limit)
        self._broker.publish(
            {
                "event": "job_finished",
                "job_id": job_id,
                "status": status.value,
                "total": counters.total,
                "changed": counters.changed,
                "warnings": counters.warnings,
                "errors": counters.errors,
                "error": error,
            }
        )

    def _prune(self, retention_limit: int) -> None:
        """Prune old history, swallowing failures so job completion still publishes.

        Retention is best-effort housekeeping: a pruning error must not stop the
        ``job_finished`` event from firing or the worker from draining its queue.
        """
        # A pruning error must not abort lifecycle completion.
        with contextlib.suppress(Exception):
            self._store.prune(retention_limit)

    def _refresh_index(self, config: Config, touched: set[Path]) -> None:
        """Re-reconcile the directories the pipeline changed so the index stays current.

        Walks only the touched directories and reconciles them with that scope, so the
        index picks up renames, deletes, rewrites, and freshly extracted subtitles while
        files outside the scope are never marked gone. A no-op when no index is
        configured or nothing changed.
        """
        if self._index is None or not touched:
            return
        paths = [str(directory) for directory in sorted(touched)]
        refreshed = scan_paths(paths, config.scan.exclude_patterns)
        self._index.reconcile(refreshed, scope=frozenset(touched))

    def _reconcile(self, scan_result: ScanResult, request: ScanRequest) -> set[Path] | None:
        """Reconcile the inventory with the index; return the paths to process.

        ``None`` (no index configured) means process everything. A dry run reconciles
        read-only so it still skips unchanged files without mutating the index.
        """
        if self._index is None:
            return None
        result = self._index.reconcile(scan_result, scope=request.scope, dry_run=request.dry_run)
        return result.process_paths

    def _scan(self, config: Config, request: ScanRequest):
        if request.scope is None:
            return scan(config)
        # A watcher-triggered run only walks the directories that changed, but still
        # respects the configured excludes so junk paths stay out of every scan.
        paths = [str(directory) for directory in sorted(request.scope)]
        return scan_paths(paths, config.scan.exclude_patterns)

    def _handle_file(
        self, job_id: int, result: FileResult, counters: _Counters, *, dry_run: bool
    ) -> None:
        counters.processed += 1
        # Keep the advertised total at or above the count actually processed. The video
        # phase result and any freshly extracted subtitles are not in the pre-run
        # inventory the total was seeded from, so without this the run could report
        # ``processed > total``.
        counters.total = max(counters.total, counters.processed)
        if result.error is not None:
            counters.errors += 1
        # A real run counts only files whose write was applied; a file the runner
        # planned to change but whose commit was skipped (validation rejected it) is
        # not a change. A dry run has no writes, so it counts the planned changes.
        if result.changed if dry_run else result.applied:
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
                "total": counters.total,
                "file": _file_event(file),
            }
        )


def _count_to_process(scan_result: ScanResult, process_paths: set[Path] | None) -> int:
    """Initial estimate of the work a run will process, for progress reporting.

    Counts inventory subtitles only. Video-phase results and freshly extracted
    subtitles are not counted here (they do not exist until the video phase runs); the
    worker raises the advertised total to cover them as they are processed, so progress
    never reports ``processed > total``.
    """
    if process_paths is None:
        return scan_result.subtitle_count
    counted = 0
    for group in scan_result.video_groups:
        counted += sum(1 for sub in group.subtitles if sub in process_paths)
    counted += sum(
        1 for standalone in scan_result.standalone_subtitles if standalone.subtitle in process_paths
    )
    return counted


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
