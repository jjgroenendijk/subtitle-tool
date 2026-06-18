"""Conversion step: ASS/SSA/VTT to SRT via pysubs2.

SRT is the lowest-common-denominator format Plex handles everywhere, so styled or
web formats are converted to it. The already-decoded text is parsed by pysubs2 with
the format taken from the source extension and re-serialised as SRT. The target
path's extension becomes ``.srt`` while the source path is unchanged: whether the
original is removed afterwards is opt-in (``delete_original_after_conversion``) and
off by default, so by default both files exist after a conversion.

A parse failure is not fatal to the file: the failure is recorded as a warning and
the original content is left for the remaining steps, in line with the rule that one
bad file never stops the run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pysubs2

from subtitle_tool.pipeline.models import ActionType

if TYPE_CHECKING:
    from subtitle_tool.config.models import Config
    from subtitle_tool.pipeline.workitem import WorkItem

# Source extensions converted to SRT, mapped to the pysubs2 format identifier.
_CONVERTIBLE = {".ass": "ass", ".ssa": "ssa", ".vtt": "vtt"}


def convert_format(item: WorkItem, config: Config) -> None:
    """Convert ``item`` from a styled/web format to SRT when enabled and applicable."""
    if not config.format.convert_to_srt:
        return
    source_format = _CONVERTIBLE.get(item.source.suffix.lower())
    if source_format is None:
        return

    # When the original is kept, a converted SRT from a previous run already sits
    # beside it; re-converting would keep minting suffixed duplicates. Skip so
    # repeated scans of an already-converted file stay inert. When the original is
    # deleted after conversion this cannot recur, so the guard is not needed there.
    converted_target = item.target.with_suffix(".srt")
    if not config.format.delete_original_after_conversion and converted_target.exists():
        return

    try:
        subs = pysubs2.SSAFile.from_string(item.text, format_=source_format)
    except (pysubs2.exceptions.Pysubs2Error, ValueError) as exc:
        item.warn(f"format conversion failed, leaving original: {exc}")
        return

    # pysubs2 is lenient: malformed input parses to zero events rather than raising.
    # An empty conversion would only produce an empty SRT, so treat it as a failure
    # and leave the original for inspection.
    if len(subs) == 0:
        item.warn("format conversion produced no subtitles, leaving original")
        return

    item.text = subs.to_string("srt")
    item.target = converted_target
    item.converted = True
    item.record(
        ActionType.CONVERT_FORMAT,
        f"convert {source_format} to srt",
    )
    if config.format.delete_original_after_conversion:
        item.remove_source = True
        item.record(
            ActionType.DELETE_ORIGINAL,
            f"delete original {item.source.name} after conversion",
        )
