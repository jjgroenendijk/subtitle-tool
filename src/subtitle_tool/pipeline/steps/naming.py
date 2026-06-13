"""Naming step: normalise the subtitle filename to Plex conventions.

Plex reads an external subtitle's language and flags from its filename:
``Movie (2020).en.srt``, ``Movie (2020).en.forced.srt``, ``Movie (2020).en.sdh.srt``.
This step rebuilds the name from the matched video's basename plus the language and
flag tokens recovered from the current subtitle name, standardising flag synonyms
(``hi``/``cc`` to ``sdh``) and their order along the way.

Language-code correction from content detection is a later milestone; here the
existing language token is preserved as-is. To avoid silently dropping a meaningful
but unrecognised suffix, a subtitle with no recognised language token whose basename
does not resemble the video's basename is left unchanged with a warning rather than
collapsed onto the bare video name.
"""

from __future__ import annotations

import re

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.workitem import WorkItem
from subtitle_tool.scanner.matching import split_subtitle_name

# Flag-token synonyms collapsed to the two flags Plex understands, emitted in a
# fixed order so the result is stable across runs.
_SDH_SYNONYMS = frozenset({"sdh", "hi", "cc"})
_FORCED_SYNONYMS = frozenset({"forced"})


def normalize_filename(item: WorkItem, config: Config) -> None:
    """Rename ``item`` to ``<video stem>[.lang][.flags]<ext>`` when it is safe to."""
    base, language, flags = split_subtitle_name(item.source)
    stem = item.video_stem if item.video_stem is not None else base

    if item.video_stem is not None and language is None and _normalize(base) != _normalize(stem):
        item.warn(
            f"cannot normalise {item.source.name}: no recognised language code and its "
            f"name does not match the video; leaving it unchanged"
        )
        return

    new_name = _plex_name(stem, language, flags, item.target.suffix)
    new_target = item.target.with_name(new_name)
    if new_target == item.target:
        return

    # A pure rename (no conversion happened) moves the file, so the old name is
    # removed. After a conversion the source is a different file whose fate the
    # conversion step already decided, so only the planned target name changes here.
    if not item.converted:
        item.remove_source = True
    item.record(ActionType.RENAME, f"rename to {new_name}")
    item.target = new_target


def _plex_name(stem: str, language: str | None, flags: list[str], suffix: str) -> str:
    parts = [stem]
    if language:
        parts.append(language)
    parts.extend(_standardize_flags(flags))
    return ".".join(parts) + suffix


def _standardize_flags(flags: list[str]) -> list[str]:
    lowered = {flag.lower() for flag in flags}
    standardized: list[str] = []
    if lowered & _FORCED_SYNONYMS:
        standardized.append("forced")
    if lowered & _SDH_SYNONYMS:
        standardized.append("sdh")
    return standardized


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())
