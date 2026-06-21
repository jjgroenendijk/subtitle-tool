"""Choose which eligible subtitle streams to extract per video/language.

Language filtering and per-variant eligibility (the ``extract`` / ``keep_embedded``
action) are decided upstream in :mod:`subtitle_tool.pipeline.video`; this module only
resolves how many of the remaining eligible streams to keep, so it has no opinion on
codecs, languages, or extraction itself and is unit-testable in isolation.

In :data:`~subtitle_tool.config.models.SelectionMode.ALL` every eligible stream is kept,
so each variant lands on its own Plex-flagged name. In
:data:`~subtitle_tool.config.models.SelectionMode.ONE_PER_LANGUAGE` the streams are
grouped by language and only the single most-preferred variant per group is kept, ranked
by the configured preference order; a variant absent from that order ranks last, and ties
are broken by the lower ffprobe stream index so the choice is stable and deterministic.
The streams it does not return are left embedded: not extracted and, since only extracted
streams are dropped, never removed during remux.

Grouping keys on the normalized ISO 639-1 code that filtering and naming use, not the raw
ffprobe tag, so bibliographic/terminologic aliases of one language (for example ``fre``
and ``fra``, both ``fr``) count as the same language and do not slip two subtitles past
the one-per-language policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_tool.config.models import SelectionMode
from subtitle_tool.pipeline.langcodes import iso639_2_to_1

if TYPE_CHECKING:
    from subtitle_tool.pipeline.ffmpeg import SubtitleStream


def select_streams(
    candidates: list[SubtitleStream],
    *,
    mode: SelectionMode,
    preference_order: list[str],
) -> list[SubtitleStream]:
    """Return the eligible ``candidates`` to extract under ``mode``.

    ``candidates`` must already be language-filtered and eligible, in ffprobe stream
    order. :data:`SelectionMode.ALL` returns them unchanged; :data:`ONE_PER_LANGUAGE`
    returns one stream per language, each the most-preferred eligible variant in that
    language, preserving the input order among the winners.
    """
    if mode is SelectionMode.ALL:
        return list(candidates)

    best: dict[str | None, SubtitleStream] = {}
    for stream in candidates:
        key = _language_key(stream)
        current = best.get(key)
        if current is None or _rank(stream, preference_order) < _rank(current, preference_order):
            best[key] = stream
    winners = {id(stream) for stream in best.values()}
    return [stream for stream in candidates if id(stream) in winners]


def _language_key(stream: SubtitleStream) -> str | None:
    """The grouping key for a stream: its ISO 639-1 code, or the raw tag if unmappable.

    Mirrors the normalization in :mod:`subtitle_tool.pipeline.video` so aliases like
    ``fre``/``fra`` group as one language; an untagged or unmappable stream keeps its
    own tag so unrelated streams are never merged.
    """
    return iso639_2_to_1(stream.language) or stream.language


def _rank(stream: SubtitleStream, preference_order: list[str]) -> int:
    """Rank a stream's variant by ``preference_order``; an unlisted variant ranks last."""
    try:
        return preference_order.index(stream.variant.value)
    except ValueError:
        return len(preference_order)
