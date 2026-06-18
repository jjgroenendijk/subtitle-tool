"""Detection step: identify the subtitle language and act on it.

Reads the subtitle text, asks ``lingua`` for the most likely language and a confidence
score, then drives two decisions: the filename language code (handed to naming via
``WorkItem.language``) and optional language filtering (delete or warn on an unwanted
language).

Every language-dependent action is gated on the confidence threshold: below it, or when
too little text exists to detect at all, nothing happens and a warning explains why, in
line with the rule that the tool never guesses on a hard-to-undo action.
"""

from __future__ import annotations

import re
from functools import lru_cache

from lingua import LanguageDetector, LanguageDetectorBuilder

from subtitle_tool.config.models import Config, FilterAction, LanguageFilterConfig
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.workitem import WorkItem
from subtitle_tool.scanner.matching import split_subtitle_name

# How much text to feed the detector. lingua is accurate on a few sentences; a window
# of a few thousand characters from the middle is plenty and keeps detection cheap.
_SAMPLE_CHARS = 3000

# Lines that carry no language signal: SRT cue indices and timing lines.
_INDEX_LINE = re.compile(r"^\d+$")
_TIMING_LINE = re.compile(r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->")
# Markup that would otherwise leak into the sample: HTML-style and ASS override tags.
_TAGS = re.compile(r"</?[a-zA-Z][^>]*>|\{[^}]*\}")


@lru_cache(maxsize=1)
def _detector() -> LanguageDetector:
    """Build the all-languages detector once and reuse it across files."""
    return LanguageDetectorBuilder.from_all_languages().build()


def detect_language(item: WorkItem, config: Config) -> None:
    """Detect ``item``'s language and apply renaming and filtering decisions."""
    language = config.language
    detected, confidence = _detect(item.text)
    confident = detected is not None and confidence >= language.min_confidence

    _, file_language, _ = split_subtitle_name(item.source)

    if not confident:
        item.warn(
            f"language detection inconclusive for {item.source.name} "
            f"(best guess {detected or 'none'} at {confidence:.2f}, "
            f"threshold {language.min_confidence:.2f}); leaving language untouched"
        )
        return

    _decide_rename(item, detected, file_language, language.rename_to_detected)
    _apply_filter(item, detected, language.filter)


def _decide_rename(
    item: WorkItem, detected: str, file_language: str | None, rename_to_detected: bool
) -> None:
    """Set ``item.language`` so naming adds a missing code or corrects a wrong one."""
    if file_language is None or file_language == detected:
        # Missing code: hand the detected one to naming. Matching code: hand it over
        # too; naming produces the identical name, so this is a harmless no-op.
        item.language = detected
        return
    if rename_to_detected:
        item.language = detected
        return
    item.warn(
        f"filename of {item.source.name} says '{file_language}' but content looks like "
        f"'{detected}'; not renaming (rename_to_detected is off)"
    )


def _apply_filter(item: WorkItem, detected: str, filter_config: LanguageFilterConfig) -> None:
    """Delete or warn about a subtitle whose detected language is unwanted."""
    if not filter_config.enabled or detected in filter_config.wanted_languages:
        return
    if filter_config.action is FilterAction.DELETE:
        item.delete_file = True
        item.record(
            ActionType.DELETE_FILTERED,
            f"delete unwanted-language subtitle ({detected})",
        )
    else:
        item.warn(
            f"{item.source.name} is in unwanted language '{detected}'; keeping it "
            f"(filter action is warn)"
        )


def _detect(text: str) -> tuple[str | None, float]:
    """Return the most likely ISO 639-1 code and its confidence for ``text``."""
    sample = _sample(text)
    if not sample:
        return None, 0.0
    values = _detector().compute_language_confidence_values(sample)
    if not values:
        return None, 0.0
    best = values[0]
    return best.language.iso_code_639_1.name.lower(), best.value


def _sample(text: str) -> str:
    """Extract dialogue text and return a window from its middle for detection.

    Sampling the middle judges content over packaging: it skips the titles, credits,
    and watermarks that cluster at the ends. Short files are detected whole.
    """
    dialogue: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or _INDEX_LINE.match(stripped) or _TIMING_LINE.search(stripped):
            continue
        dialogue.append(_TAGS.sub("", stripped))
    content = " ".join(part for part in dialogue if part).strip()
    if len(content) <= _SAMPLE_CHARS:
        return content
    start = (len(content) - _SAMPLE_CHARS) // 2
    return content[start : start + _SAMPLE_CHARS]
