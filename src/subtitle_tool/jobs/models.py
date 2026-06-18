"""Records describing a stored job and its per-file outcomes.

These are the read models the store returns and the web layer renders. They are
deliberately plain dataclasses, separate from the live
:class:`~subtitle_tool.pipeline.models.FileResult` produced during a run: a stored
record carries an integer id and timestamps and survives past the worker thread
that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class JobStatus(StrEnum):
    """Lifecycle state of a job."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # A job left RUNNING by a process that stopped mid-run. Found and marked on the
    # next startup; never resumed, since the idempotent steps and the next scheduled
    # scan pick up whatever was left undone.
    INTERRUPTED = "interrupted"
    # A job the user stopped from the UI. Distinct from INTERRUPTED (a crash/restart):
    # cancellation is cooperative and intentional, observed at a safe boundary between
    # files, so no partial write is left behind. Any queued follow-up is dropped.
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class JobFile:
    """One file's outcome within a job, as stored."""

    source: str
    target: str
    actions: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.actions)


@dataclass(frozen=True)
class Job:
    """A job summary plus, when loaded in detail, its per-file results.

    ``files`` is empty in list views and populated when a single job is loaded;
    the count fields are always present so summaries need no file rows.
    """

    id: int
    mode: str
    status: JobStatus
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    total_files: int = 0
    changed_files: int = 0
    warning_count: int = 0
    error_files: int = 0
    files: list[JobFile] = field(default_factory=list)

    @property
    def dry_run(self) -> bool:
        return self.mode == "dry-run"
