"""Result models for the subtitle pipeline.

A pipeline run produces, for each subtitle file, the ordered list of actions that
were taken (or, in dry-run, would be taken), any warnings explaining what the
pipeline declined to do, and an error if the file could not be processed at all.
These models are the reporting surface the CLI and (later) the web UI render; they
are deliberately separate from the mutable :class:`~subtitle_tool.pipeline.runner`
work item used while a file is being processed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ActionType(StrEnum):
    """The kinds of change the pipeline can make to a subtitle file."""

    CONVERT_ENCODING = "convert_encoding"
    CONVERT_FORMAT = "convert_format"
    CLEANUP = "cleanup"
    RENAME = "rename"
    SYNC_CORRECT = "sync_correct"
    DELETE_ORIGINAL = "delete_original"
    DELETE_FILTERED = "delete_filtered"
    EXTRACT_SUBTITLE = "extract_subtitle"
    REMUX = "remux"


@dataclass(frozen=True)
class Action:
    """One change a pipeline step decided to make, with a human-readable summary."""

    type: ActionType
    description: str


@dataclass(frozen=True)
class FileResult:
    """The outcome of running the pipeline against a single subtitle file.

    ``actions`` are the changes the runner decided on; in a dry run they are what a
    real run would do, in a real run what it attempted. ``applied`` records whether a
    real run's write actually reached disk: it stays ``False`` in a dry run (nothing
    is written) and for a real run whose commit was skipped because the safety
    validator rejected the result or the write failed, leaving the original in place.
    """

    source: Path
    target: Path
    actions: list[Action] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    applied: bool = False

    @property
    def changed(self) -> bool:
        """Whether the pipeline made (or planned) any change to this file."""
        return bool(self.actions)


@dataclass(frozen=True)
class PipelineResult:
    """The outcome of a pipeline run across every subtitle in a scan."""

    file_results: list[FileResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def changed_files(self) -> list[FileResult]:
        """Files this run changed: planned in a dry run, written in a real run.

        A real run counts only files whose write was actually applied, so a file the
        runner planned to change but whose commit was skipped (the safety validator
        rejected the result, or the write failed) is reported under
        :attr:`skipped_files` rather than counted as changed here.
        """
        if self.dry_run:
            return [result for result in self.file_results if result.changed]
        return [result for result in self.file_results if result.applied]

    @property
    def skipped_files(self) -> list[FileResult]:
        """Real-run files the runner planned to change but did not write.

        Empty in a dry run (nothing is ever written). In a real run these are files
        with planned actions whose commit was skipped, leaving the original on disk;
        each carries a warning explaining why. Files that failed to process at all are
        reported under :attr:`errors`, not here.
        """
        if self.dry_run:
            return []
        return [
            result
            for result in self.file_results
            if result.actions and not result.applied and result.error is None
        ]

    @property
    def warnings(self) -> list[str]:
        collected: list[str] = []
        for result in self.file_results:
            collected.extend(result.warnings)
        return collected

    @property
    def errors(self) -> list[FileResult]:
        return [result for result in self.file_results if result.error is not None]
