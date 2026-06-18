"""Mutable state threaded through the pipeline steps for one subtitle file.

Steps mutate the item in place and record an :class:`Action` per change (or a warning
for anything they decline to do); the runner writes only when ``actions`` is non-empty.

Field notes worth keeping:

- ``output_encoding`` is the original detected encoding when UTF-8 conversion is off,
  so a later cleanup or rename does not silently transcode the bytes.
- ``language`` is the code detection hands to naming, left ``None`` to preserve the
  existing filename token.
- ``delete_file`` makes the runner remove the file (unwanted language) instead of
  writing a result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from subtitle_tool.pipeline.models import Action, ActionType

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class WorkItem:
    """In-flight state for a single subtitle file as it passes through the steps."""

    source: Path
    target: Path
    text: str
    video_stem: str | None = None
    video: Path | None = None
    output_encoding: str = "utf-8"
    converted: bool = False
    remove_source: bool = False
    language: str | None = None
    delete_file: bool = False
    actions: list[Action] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def record(self, action_type: ActionType, description: str) -> None:
        self.actions.append(Action(type=action_type, description=description))

    def warn(self, message: str) -> None:
        self.warnings.append(message)
