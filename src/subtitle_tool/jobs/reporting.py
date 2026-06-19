"""Reporting helpers for the worker: counters, result mapping, and event payloads.

The worker owns job orchestration; the bookkeeping around a run -- tallying per-file
outcomes, mapping a pipeline ``FileResult`` to a stored ``JobFile``, and shaping the
SSE event payloads -- is presentation and reporting detail that would otherwise
accumulate in the worker and make the orchestration harder to follow. It lives here so
the worker stays focused on the lifecycle and a change to what a run counts or what an
event carries is a change to this module alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from subtitle_tool.jobs.models import JobFile
from subtitle_tool.pipeline.models import ActionType

if TYPE_CHECKING:
    from pathlib import Path

    from subtitle_tool.pipeline import FileResult
    from subtitle_tool.scanner.models import ScanResult


@dataclass
class Counters:
    """Running tallies for one job, reported in logs, the store, and SSE events."""

    processed: int = 0
    changed: int = 0
    warnings: int = 0
    errors: int = 0
    # The advertised work total. Seeded from the inventory before the run, then
    # raised so it never trails ``processed``: the video phase and the subtitles it
    # extracts are work discovered during the run, not in the pre-run inventory, so a
    # fixed total would let progress report more processed files than the total.
    total: int = 0
    # Inventory the scan saw, recorded before reconcile so it reports what the run
    # covered regardless of how much of it turned out to be new or changed work.
    videos_found: int = 0
    subtitles_found: int = 0
    # Subtitles the language filter removed (delete action). Warn-mode unwanted
    # subtitles are kept and surface as warnings instead.
    unwanted: int = 0

    def record_file(self, result: FileResult, *, dry_run: bool) -> None:
        """Fold one pipeline ``FileResult`` into the running tallies.

        Keeps the advertised total at or above the count actually processed: the video
        phase result and any freshly extracted subtitles are not in the pre-run
        inventory the total was seeded from, so without this a run could report
        ``processed > total``. A real run counts only files whose write was applied; a
        file the runner planned to change but whose commit was skipped (validation
        rejected it) is not a change. A dry run has no writes, so it counts planned
        changes and planned filtered deletes, mirroring how a real run counts applied
        ones.
        """
        self.processed += 1
        self.total = max(self.total, self.processed)
        if result.error is not None:
            self.errors += 1
        changed = result.changed if dry_run else result.applied
        if changed:
            self.changed += 1
        self.warnings += len(result.warnings)
        if changed and any(action.type is ActionType.DELETE_FILTERED for action in result.actions):
            self.unwanted += 1


def count_to_process(scan_result: ScanResult, process_paths: set[Path] | None) -> int:
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


def to_job_file(result: FileResult) -> JobFile:
    """Map a pipeline ``FileResult`` to the ``JobFile`` record the store persists."""
    return JobFile(
        source=str(result.source),
        target=str(result.target),
        actions=[(action.type.value, action.description) for action in result.actions],
        warnings=list(result.warnings),
        error=result.error,
    )


def file_event(file: JobFile) -> dict[str, Any]:
    """Shape the per-file SSE event payload from a stored ``JobFile``."""
    return {
        "source": file.source,
        "target": file.target,
        "changed": file.changed,
        "actions": [list(action) for action in file.actions],
        "warnings": file.warnings,
        "error": file.error,
    }
