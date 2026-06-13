"""Mutable state threaded through the pipeline steps for one subtitle file.

The runner loads a file once into a :class:`WorkItem` and hands it to each enabled
step in dependency order. Steps mutate the item in place: they update ``text`` and
``target`` as they transform the content and its name, append an :class:`Action`
for every change they make, and append a warning for anything they decline to do.
The runner reads ``actions`` to decide whether a write is needed (no actions means
the file is already clean, so nothing is written) and ``target``/``remove_source``
to decide where the result goes and whether the original is removed. ``video`` is the
matched video the sync step aligns against (``None`` for a standalone subtitle, which
is never sync-corrected). ``language``
is the language code the detection step decided the naming step should write (left
``None`` when the existing filename token should be preserved); ``delete_file`` is
set by language filtering when the file is in an unwanted language and configured to
be deleted, in which case the runner removes it instead of writing a result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from subtitle_tool.pipeline.models import Action, ActionType


@dataclass
class WorkItem:
    """In-flight state for a single subtitle file as it passes through the steps."""

    source: Path
    target: Path
    text: str
    video_stem: str | None = None
    video: Path | None = None
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
