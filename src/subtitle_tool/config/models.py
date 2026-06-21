"""Persisted configuration model.

This describes every setting the user edits through the web UI and that is stored
in the config file in the ``/config`` volume. Defaults are conservative: every
destructive option is off until enabled, matching the safety rules in
``docs/architecture.md``.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ISO 639-1 two-letter language codes; full validation against a table is overkill,
# a shape check catches the common mistakes (region tags, three-letter codes, casing).
_LANG_CODE = re.compile(r"^[a-z]{2}$")


def _validate_language_codes(codes: list[str]) -> list[str]:
    invalid = [c for c in codes if not _LANG_CODE.match(c)]
    if invalid:
        raise ValueError(f"language codes must be lowercase ISO 639-1 (two letters); got {invalid}")
    return codes


# The embedded subtitle variants the extraction config can reference, mirroring
# ``SubtitleVariant`` in ``subtitle_tool.pipeline.stream_variants`` (kept as plain strings
# here so the config layer does not import the pipeline package). A drift test asserts the
# two stay in sync.
_VARIANT_NAMES = ("normal", "forced", "sdh", "unknown")


def _validate_preference_order(order: list[str]) -> list[str]:
    invalid = [v for v in order if v not in _VARIANT_NAMES]
    if invalid:
        raise ValueError(
            f"preference_order entries must be one of {list(_VARIANT_NAMES)}; got {invalid}"
        )
    if len(order) != len(set(order)):
        raise ValueError("preference_order must not list a variant more than once")
    return order


class StrictModel(BaseModel):
    """Base model that rejects unknown keys so typos in the config file are caught."""

    model_config = ConfigDict(extra="forbid")


class FilterAction(StrEnum):
    """What to do with a subtitle in an unwanted language."""

    DELETE = "delete"
    WARN = "warn"


class StreamAction(StrEnum):
    """What to do with an embedded subtitle stream of a given variant.

    ``extract`` writes the stream to an external SRT and, when remux is enabled, drops
    it from the remuxed video. ``keep_embedded`` leaves the stream in the video
    untouched: it is neither extracted nor dropped during remux.
    """

    EXTRACT = "extract"
    KEEP_EMBEDDED = "keep_embedded"


class SelectionMode(StrEnum):
    """How many eligible variants to keep per video/language.

    ``all`` extracts every eligible stream, so each variant lands on its own
    Plex-flagged name. ``one_per_language`` keeps only the single most-preferred
    eligible variant per language (ranked by ``preference_order``), so a video ends
    with one external subtitle per language instead of one per variant. Eligibility
    (the per-variant ``extract`` / ``keep_embedded`` action) and language filtering are
    applied first; this only decides how many of the remaining eligible streams to keep.
    """

    ALL = "all"
    ONE_PER_LANGUAGE = "one_per_language"


class ScanConfig(StrictModel):
    """Which paths are scanned and what is excluded."""

    media_paths: list[str] = Field(
        default_factory=list,
        description="Directories scanned recursively for videos and subtitles.",
        json_schema_extra={"widget": "path"},
    )
    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns for paths or filenames kept out of scans.",
    )
    interval_hours: float = Field(
        default=6.0,
        gt=0,
        description="Interval between scheduled scans, in hours.",
    )
    scan_on_startup: bool = Field(
        default=False,
        description="Run a scan once when the container starts.",
    )


class WatcherConfig(StrictModel):
    """inotify-based filesystem watching of the media paths."""

    enabled: bool = Field(default=True, description="Watch media paths for changes.")
    stability_window_seconds: float = Field(
        default=30.0,
        gt=0,
        description="A changed file is queued only after its size and mtime are "
        "stable for this long, so in-progress copies are never processed.",
    )


class ExtractionConfig(StrictModel):
    """Extraction of embedded text subtitle streams to external SRT files."""

    enabled: bool = Field(default=False, description="Extract embedded text streams.")
    languages: list[str] = Field(
        default_factory=list,
        description="Language codes to extract; empty means all text streams.",
        json_schema_extra={"widget": "language"},
    )
    normal: StreamAction = Field(
        default=StreamAction.EXTRACT,
        description="What to do with normal/full subtitle streams.",
    )
    forced: StreamAction = Field(
        default=StreamAction.EXTRACT,
        description="What to do with forced subtitle streams (named <video>.<lang>.forced.srt).",
    )
    sdh: StreamAction = Field(
        default=StreamAction.EXTRACT,
        description="What to do with SDH/hearing-impaired/caption streams "
        "(named <video>.<lang>.sdh.srt).",
    )
    unknown: StreamAction = Field(
        default=StreamAction.KEEP_EMBEDDED,
        description="What to do with streams whose variant cannot be determined or whose "
        "metadata conflicts. Kept embedded by default so an ambiguous stream is never "
        "guessed into a destructive action.",
    )
    selection_mode: SelectionMode = Field(
        default=SelectionMode.ALL,
        description="Keep all eligible variants, or only the single most preferred one "
        "per video/language (ranked by preference_order).",
    )
    preference_order: list[str] = Field(
        default_factory=lambda: ["normal", "sdh", "forced"],
        description="Variant preference, best first, used when selection_mode is "
        "one_per_language. Values: normal, sdh, forced, unknown (one per line).",
    )
    remux: bool = Field(
        default=False,
        description="Remux the video to drop extracted streams afterwards.",
    )
    delete_original_video: bool = Field(
        default=False,
        description="Delete the source video after a successful remux.",
    )

    _check_langs = field_validator("languages")(_validate_language_codes)
    _check_preference = field_validator("preference_order")(_validate_preference_order)

    @model_validator(mode="after")
    def _delete_requires_remux(self) -> ExtractionConfig:
        if self.delete_original_video and not self.remux:
            raise ValueError(
                "extraction.delete_original_video requires extraction.remux to be enabled"
            )
        return self


class FormatConfig(StrictModel):
    """Encoding normalization and format conversion."""

    convert_to_utf8: bool = Field(
        default=True, description="Normalize text subtitle encoding to UTF-8."
    )
    convert_to_srt: bool = Field(default=True, description="Convert ASS/SSA/VTT subtitles to SRT.")
    delete_original_after_conversion: bool = Field(
        default=False,
        description="Delete the source file after a successful format conversion.",
    )

    @model_validator(mode="after")
    def _delete_requires_conversion(self) -> FormatConfig:
        if self.delete_original_after_conversion and not self.convert_to_srt:
            raise ValueError(
                "format.delete_original_after_conversion requires format.convert_to_srt "
                "to be enabled"
            )
        return self


class LanguageFilterConfig(StrictModel):
    """Optional filtering of subtitles to a set of wanted languages."""

    enabled: bool = Field(default=False, description="Filter out unwanted languages.")
    wanted_languages: list[str] = Field(
        default_factory=list,
        description="Language codes to keep when filtering is enabled.",
        json_schema_extra={"widget": "language"},
    )
    action: FilterAction = Field(
        default=FilterAction.WARN,
        description="Delete unwanted-language subtitles or keep them with a warning.",
    )

    _check_langs = field_validator("wanted_languages")(_validate_language_codes)

    @model_validator(mode="after")
    def _enabled_requires_languages(self) -> LanguageFilterConfig:
        if self.enabled and not self.wanted_languages:
            raise ValueError(
                "language.filter.wanted_languages must list at least one code when "
                "language.filter.enabled is true"
            )
        return self


class LanguageConfig(StrictModel):
    """Language detection and the actions gated on it."""

    min_confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum detection confidence for language-dependent actions.",
    )
    rename_to_detected: bool = Field(
        default=True,
        description="Rename when the filename language code disagrees with detection "
        "and confidence is high.",
    )
    filter: LanguageFilterConfig = Field(default_factory=LanguageFilterConfig)


class SyncConfig(StrictModel):
    """Correction of out-of-sync text subtitles against the video's audio.

    Off by default: ffsubsync runs per video-matched subtitle and a correction is
    applied only when all three gates pass, otherwise the original is kept and a
    warning is recorded. The thresholds are the safety margin that keeps a wrong
    guess from shifting a subtitle that was fine.
    """

    enabled: bool = Field(
        default=False, description="Correct out-of-sync subtitles against the video audio."
    )
    min_offset_seconds: float = Field(
        default=0.5,
        ge=0.0,
        description="Apply a correction only when the measured shift is at least this "
        "large; smaller shifts are treated as already in sync.",
    )
    max_offset_seconds: float = Field(
        default=60.0,
        gt=0.0,
        description="Safety cap: a measured shift larger than this is rejected as "
        "untrustworthy and the original is kept.",
    )
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum ffsubsync alignment score to accept a correction; a lower "
        "score is treated as an untrustworthy result and the original is kept.",
    )
    timeout_seconds: float = Field(
        default=300.0,
        gt=0.0,
        description="Per-file time budget for ffsubsync; on timeout the file is skipped "
        "with a warning and the job continues.",
    )

    @model_validator(mode="after")
    def _cap_above_minimum(self) -> SyncConfig:
        if self.max_offset_seconds <= self.min_offset_seconds:
            raise ValueError("sync.max_offset_seconds must be greater than sync.min_offset_seconds")
        return self


class CleanupConfig(StrictModel):
    """Content cleanup rules, each individually toggleable."""

    remove_ads: bool = Field(default=True, description="Remove known ad/watermark lines.")
    remove_empty_blocks: bool = Field(
        default=True, description="Remove empty or broken cue blocks."
    )
    remove_duplicate_blocks: bool = Field(
        default=True, description="Remove duplicate consecutive blocks."
    )
    remove_artifacts: bool = Field(
        default=True, description="Remove lone music notes and punctuation leftovers."
    )
    strip_styling: bool = Field(
        default=False, description="Strip styling tags (italics, color, positioning)."
    )


class HistoryConfig(StrictModel):
    """Job history retention."""

    retention_limit: int = Field(
        default=100,
        ge=1,
        description="Maximum number of past jobs kept in the SQLite history.",
    )


class Config(StrictModel):
    """Top-level persisted configuration."""

    scan: ScanConfig = Field(default_factory=ScanConfig)
    watcher: WatcherConfig = Field(default_factory=WatcherConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    format: FormatConfig = Field(default_factory=FormatConfig)
    language: LanguageConfig = Field(default_factory=LanguageConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
