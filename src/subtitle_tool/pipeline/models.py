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
    """The outcome of running the pipeline against a single subtitle file."""

    source: Path
    target: Path
    actions: list[Action] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

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
        return [result for result in self.file_results if result.changed]

    @property
    def warnings(self) -> list[str]:
        collected: list[str] = []
        for result in self.file_results:
            collected.extend(result.warnings)
        return collected

    @property
    def errors(self) -> list[FileResult]:
        return [result for result in self.file_results if result.error is not None]
