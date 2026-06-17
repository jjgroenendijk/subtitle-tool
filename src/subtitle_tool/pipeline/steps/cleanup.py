"""Cleanup step: remove ads, empty/broken/duplicate blocks, and artifacts.

Operates on SRT text through the tolerant block model in
:mod:`subtitle_tool.pipeline.srt`. Each rule is independently toggleable in the
config and records its own :class:`ActionType.CLEANUP` action describing what it
removed, so the report shows which rule fired. Rules run in a fixed order: ad lines
first (an ad-only cue then becomes empty), then empty/broken blocks, then
consecutive duplicates, then leftover artifacts, then optional style stripping.

The step only touches files whose content is SRT. A non-SRT file that was not
converted (because conversion is disabled) is left untouched here, since the block
model assumes SRT.
"""

from __future__ import annotations

import re

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.srt import Block, compose_srt, parse_srt
from subtitle_tool.pipeline.workitem import WorkItem

# Known subtitle ad and watermark lines. Kept conservative: provider names, URLs,
# and the classic credit phrasings, which effectively never occur in real dialogue.
# A bare line such as a TLD match is intentionally not included to avoid removing
# genuine dialogue that happens to mention a website.
_AD_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"opensubtitles",
        r"subscene",
        r"addic7ed",
        r"podnapisi",
        r"yifysubtitles?",
        r"www\.\S+",
        r"https?://\S+",
        r"\bsubtitles?\s+by\b",
        r"\bsubs?\s+by\b",
        r"sync(?:ed|hronized)?\s+(?:and\s+corrected\s+)?by",
        r"\bcorrected\s+by\b",
        r"\bcaptioning\s+by\b",
        r"\bencoded\s+by\b",
        r"\bripped\s+by\b",
        r"\bdownloaded\s+from\b",
        r"support\s+us\s+and\s+become",
        r"advertise\s+your\s+product",
        r"rate\s+this\s+subtitle",
    )
]

# Lone artifacts: a line of nothing but music symbols, or nothing but stray
# punctuation/dashes left behind once surrounding text is gone.
_MUSIC_ONLY = re.compile(r"^[\s♪♫♩♪#*]+$")
# The class intentionally lists the EN DASH and EM DASH that appear in subtitle
# punctuation lines; the visual ambiguity with HYPHEN-MINUS is the point.
_PUNCTUATION_ONLY = re.compile(r"^[\s\-–—_.…•·]+$")  # noqa: RUF001

# Styling: HTML-style tags (<i>, </i>, <font ...>) and ASS override blocks ({\an8}).
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_ASS_OVERRIDE = re.compile(r"\{[^}]*\}")


def clean(item: WorkItem, config: Config) -> None:
    """Apply the enabled cleanup rules to ``item`` when its content is SRT."""
    if item.target.suffix.lower() != ".srt":
        return

    blocks = parse_srt(item.text)
    cleanup = config.cleanup

    if cleanup.remove_ads:
        blocks = _apply_count(item, blocks, _strip_ad_lines, "ad/watermark line(s)")
    if cleanup.remove_empty_blocks:
        blocks = _apply_count(item, blocks, _drop_empty_blocks, "empty or broken block(s)")
    if cleanup.remove_duplicate_blocks:
        blocks = _apply_count(item, blocks, _drop_consecutive_duplicates, "duplicate block(s)")
    if cleanup.remove_artifacts:
        blocks = _apply_count(item, blocks, _strip_artifacts, "artifact line(s)")
    if cleanup.strip_styling:
        blocks = _apply_count(item, blocks, _strip_styling, "styling tag(s)")

    if any(action.type is ActionType.CLEANUP for action in item.actions):
        item.text = compose_srt(blocks)


def _apply_count(item: WorkItem, blocks, rule, noun: str):
    """Run ``rule``, record a CLEANUP action when it removed anything, return blocks."""
    cleaned, removed = rule(blocks)
    if removed:
        item.record(ActionType.CLEANUP, f"removed {removed} {noun}")
    return cleaned


def _strip_ad_lines(blocks: list[Block]) -> tuple[list[Block], int]:
    removed = 0
    result: list[Block] = []
    for block in blocks:
        kept_lines = [line for line in block.lines if not _is_ad(line)]
        removed += len(block.lines) - len(kept_lines)
        block.lines = kept_lines
        # An ad-only cue is now empty; drop it entirely rather than leave a hole.
        if block.timing is not None and not any(line.strip() for line in kept_lines):
            continue
        result.append(block)
    return result, removed


def _drop_empty_blocks(blocks: list[Block]) -> tuple[list[Block], int]:
    result = [block for block in blocks if not (block.is_broken or block.is_empty)]
    return result, len(blocks) - len(result)


def _drop_consecutive_duplicates(blocks: list[Block]) -> tuple[list[Block], int]:
    result: list[Block] = []
    removed = 0
    previous_text: str | None = None
    for block in blocks:
        normalized = block.text.strip()
        if normalized and normalized == previous_text:
            removed += 1
            continue
        result.append(block)
        previous_text = normalized
    return result, removed


def _strip_artifacts(blocks: list[Block]) -> tuple[list[Block], int]:
    removed = 0
    result: list[Block] = []
    for block in blocks:
        kept_lines = [line for line in block.lines if not _is_artifact(line)]
        removed += len(block.lines) - len(kept_lines)
        block.lines = kept_lines
        if block.timing is not None and not any(line.strip() for line in kept_lines):
            continue
        result.append(block)
    return result, removed


def _strip_styling(blocks: list[Block]) -> tuple[list[Block], int]:
    removed = 0
    for block in blocks:
        new_lines = []
        for line in block.lines:
            stripped = _ASS_OVERRIDE.sub("", _HTML_TAG.sub("", line))
            if stripped != line:
                removed += 1
            new_lines.append(stripped)
        block.lines = new_lines
    return blocks, removed


def _is_ad(line: str) -> bool:
    return any(pattern.search(line) for pattern in _AD_PATTERNS)


def _is_artifact(line: str) -> bool:
    text = line.strip()
    if not text:
        return False
    return bool(_MUSIC_ONLY.match(text) or _PUNCTUATION_ONLY.match(text))
