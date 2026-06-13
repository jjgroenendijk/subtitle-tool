"""Result models for a library scan.

A scan produces an inventory, not actions: a list of video groups (a video and
the subtitle files paired with it) and a list of standalone subtitles (subtitle
files that could not be confidently paired). Both kinds carry structured warnings
explaining anything the matcher was unsure about, so the pipeline and the UI can
report problems without re-deriving them.

These models hold ``Path`` values and are produced at runtime; they are not part
of the persisted TOML config. They are frozen so a scan result is a stable
snapshot.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class WarningReason(StrEnum):
    """Why the matcher could not confidently pair a subtitle with a video."""

    NO_MATCH = "no_match"
    AMBIGUOUS_MATCH = "ambiguous_match"


class MatchWarning(BaseModel):
    """A structured reason a subtitle was left standalone."""

    model_config = ConfigDict(frozen=True)

    reason: WarningReason
    message: str
    subtitle: Path


class VideoGroup(BaseModel):
    """A video and the subtitle files paired with it."""

    model_config = ConfigDict(frozen=True)

    video: Path
    subtitles: list[Path] = Field(default_factory=list)
    warnings: list[MatchWarning] = Field(default_factory=list)


class StandaloneSubtitle(BaseModel):
    """A subtitle file that could not be confidently paired with a video."""

    model_config = ConfigDict(frozen=True)

    subtitle: Path
    warnings: list[MatchWarning] = Field(default_factory=list)


class ScanResult(BaseModel):
    """The full inventory produced by a scan."""

    model_config = ConfigDict(frozen=True)

    video_groups: list[VideoGroup] = Field(default_factory=list)
    standalone_subtitles: list[StandaloneSubtitle] = Field(default_factory=list)

    @property
    def warnings(self) -> list[MatchWarning]:
        """Every warning across all groups and standalone subtitles."""
        collected: list[MatchWarning] = []
        for group in self.video_groups:
            collected.extend(group.warnings)
        for standalone in self.standalone_subtitles:
            collected.extend(standalone.warnings)
        return collected
