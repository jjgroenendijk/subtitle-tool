"""Tests for per-video/language eligible-stream selection.

These exercise the selection rules directly, independent of ffmpeg, the config form,
and extraction itself, so the preference/fallback logic has its own focused coverage.
"""

from __future__ import annotations

from subtitle_tool.config.models import SelectionMode
from subtitle_tool.pipeline.ffmpeg import SubtitleStream
from subtitle_tool.pipeline.stream_selection import select_streams
from subtitle_tool.pipeline.stream_variants import SubtitleVariant

_PREFERENCE = ["normal", "sdh", "forced"]


def _stream(index: int, language: str | None, variant: SubtitleVariant) -> SubtitleStream:
    return SubtitleStream(index=index, codec="subrip", language=language, variant=variant)


def test_all_mode_keeps_every_eligible_stream() -> None:
    candidates = [
        _stream(2, "eng", SubtitleVariant.NORMAL),
        _stream(3, "eng", SubtitleVariant.FORCED),
        _stream(4, "eng", SubtitleVariant.SDH),
    ]

    selected = select_streams(candidates, mode=SelectionMode.ALL, preference_order=_PREFERENCE)

    assert selected == candidates


def test_one_per_language_prefers_normal_over_sdh() -> None:
    normal = _stream(2, "eng", SubtitleVariant.NORMAL)
    sdh = _stream(3, "eng", SubtitleVariant.SDH)

    selected = select_streams(
        [sdh, normal], mode=SelectionMode.ONE_PER_LANGUAGE, preference_order=_PREFERENCE
    )

    assert selected == [normal]


def test_one_per_language_falls_back_to_sdh_when_no_normal() -> None:
    sdh = _stream(3, "eng", SubtitleVariant.SDH)
    forced = _stream(4, "eng", SubtitleVariant.FORCED)

    selected = select_streams(
        [sdh, forced], mode=SelectionMode.ONE_PER_LANGUAGE, preference_order=_PREFERENCE
    )

    assert selected == [sdh]


def test_one_per_language_is_independent_per_language() -> None:
    en_normal = _stream(2, "eng", SubtitleVariant.NORMAL)
    en_sdh = _stream(3, "eng", SubtitleVariant.SDH)
    fr_sdh = _stream(4, "fra", SubtitleVariant.SDH)

    selected = select_streams(
        [en_normal, en_sdh, fr_sdh],
        mode=SelectionMode.ONE_PER_LANGUAGE,
        preference_order=_PREFERENCE,
    )

    assert selected == [en_normal, fr_sdh]


def test_one_per_language_breaks_ties_by_lower_index() -> None:
    # Two normal English streams tie on preference; the lower ffprobe index wins.
    first = _stream(2, "eng", SubtitleVariant.NORMAL)
    second = _stream(3, "eng", SubtitleVariant.NORMAL)

    selected = select_streams(
        [first, second], mode=SelectionMode.ONE_PER_LANGUAGE, preference_order=_PREFERENCE
    )

    assert selected == [first]


def test_one_per_language_groups_iso6392_aliases_together() -> None:
    # fre (bibliographic) and fra (terminologic) both normalize to fr for filtering and
    # naming, so they must count as one language and not slip two French subtitles past.
    fre_normal = _stream(2, "fre", SubtitleVariant.NORMAL)
    fra_sdh = _stream(3, "fra", SubtitleVariant.SDH)

    selected = select_streams(
        [fre_normal, fra_sdh], mode=SelectionMode.ONE_PER_LANGUAGE, preference_order=_PREFERENCE
    )

    assert selected == [fre_normal]


def test_variant_absent_from_preference_order_ranks_last() -> None:
    # forced is not listed; the listed normal is preferred even though forced comes first.
    forced = _stream(2, "eng", SubtitleVariant.FORCED)
    normal = _stream(3, "eng", SubtitleVariant.NORMAL)

    selected = select_streams(
        [forced, normal], mode=SelectionMode.ONE_PER_LANGUAGE, preference_order=["normal", "sdh"]
    )

    assert selected == [normal]
