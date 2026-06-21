"""Classify an embedded subtitle stream into a Plex-style variant.

A video can carry several subtitle streams in one language: a normal/full stream, an
SDH/hearing-impaired (or closed-caption) stream, and a forced stream. Distinguishing
them is what lets extraction name the external files ``.srt``, ``.sdh.srt``, and
``.forced.srt`` instead of collapsing same-language streams into numeric collision
suffixes, and what lets the user choose a per-variant extraction action.

Classification is deterministic and conservative. ffprobe stream dispositions are the
authority: ``forced`` means forced, ``hearing_impaired`` or ``captions`` means SDH.
Only when no disposition is set do we fall back to the stream title, recognising just a
few unambiguous labels. Anything contradictory — both a forced and an SDH signal — is
reported as :data:`SubtitleVariant.UNKNOWN` so the caller handles it under the
unknown-stream policy rather than guessing into a destructive action.

This is a focused, pipeline-local concern kept out of :mod:`subtitle_tool.pipeline.ffmpeg`
(which only wraps the subprocess calls) so the rules have their own home and unit tests.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# Clear, unambiguous title labels recognised only when dispositions are silent. Short
# tokens use word boundaries so a stray "cc" inside another word does not match.
_FORCED_TITLE = re.compile(r"\bforced\b", re.IGNORECASE)
_SDH_TITLE = re.compile(r"\bsdh\b|hearing[ -]?impaired|\bcc\b|caption", re.IGNORECASE)


class SubtitleVariant(StrEnum):
    """The variant of an embedded subtitle stream, as used for naming and config."""

    NORMAL = "normal"
    FORCED = "forced"
    SDH = "sdh"
    UNKNOWN = "unknown"

    @property
    def flag(self) -> str | None:
        """The Plex filename flag for this variant, or ``None`` when it carries none.

        Normal streams carry no flag (``Movie.en.srt``); an unknown stream is named
        without a flag too, since guessing one would mislabel it.
        """
        return {SubtitleVariant.FORCED: "forced", SubtitleVariant.SDH: "sdh"}.get(self)


def classify_variant(
    disposition: Mapping[str, object] | None, title: str | None
) -> SubtitleVariant:
    """Classify a stream from its ffprobe ``disposition`` map and ``title`` tag.

    Dispositions win: a ``forced`` disposition gives :data:`SubtitleVariant.FORCED`, a
    ``hearing_impaired`` or ``captions`` disposition gives :data:`SubtitleVariant.SDH`.
    A stream flagged both forced and SDH is contradictory and returns
    :data:`SubtitleVariant.UNKNOWN`. When no disposition is set the title is consulted
    for an unambiguous label; a title carrying both a forced and an SDH label is also
    :data:`SubtitleVariant.UNKNOWN`. Anything else is :data:`SubtitleVariant.NORMAL`.
    """
    disposition = disposition or {}
    forced = _is_set(disposition.get("forced"))
    sdh = _is_set(disposition.get("hearing_impaired")) or _is_set(disposition.get("captions"))
    if forced and sdh:
        return SubtitleVariant.UNKNOWN
    if forced:
        return SubtitleVariant.FORCED
    if sdh:
        return SubtitleVariant.SDH
    return _classify_title(title)


def _classify_title(title: str | None) -> SubtitleVariant:
    if not title:
        return SubtitleVariant.NORMAL
    forced = bool(_FORCED_TITLE.search(title))
    sdh = bool(_SDH_TITLE.search(title))
    if forced and sdh:
        return SubtitleVariant.UNKNOWN
    if forced:
        return SubtitleVariant.FORCED
    if sdh:
        return SubtitleVariant.SDH
    return SubtitleVariant.NORMAL


def _is_set(value: object) -> bool:
    """Whether an ffprobe disposition flag is set (reported as ``1``)."""
    return value in (1, "1", True)
