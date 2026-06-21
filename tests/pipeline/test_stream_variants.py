"""Tests for deterministic embedded-stream variant classification."""

from __future__ import annotations

import pytest

from subtitle_tool.pipeline.stream_variants import SubtitleVariant, classify_variant


def test_no_signals_is_normal() -> None:
    assert classify_variant({}, None) is SubtitleVariant.NORMAL
    assert classify_variant(None, None) is SubtitleVariant.NORMAL
    assert classify_variant({"forced": 0, "hearing_impaired": 0}, "English") is (
        SubtitleVariant.NORMAL
    )


def test_forced_disposition_is_forced() -> None:
    assert classify_variant({"forced": 1}, None) is SubtitleVariant.FORCED


@pytest.mark.parametrize("flag", ["hearing_impaired", "captions"])
def test_sdh_dispositions_are_sdh(flag: str) -> None:
    assert classify_variant({flag: 1}, None) is SubtitleVariant.SDH


def test_dispositions_beat_title_heuristics() -> None:
    # A title claiming "Forced" cannot override a hearing_impaired disposition.
    assert classify_variant({"hearing_impaired": 1}, "English Forced") is SubtitleVariant.SDH


def test_conflicting_dispositions_are_unknown() -> None:
    assert classify_variant({"forced": 1, "hearing_impaired": 1}, None) is SubtitleVariant.UNKNOWN


def test_title_fallback_when_dispositions_silent() -> None:
    assert classify_variant({}, "English Forced") is SubtitleVariant.FORCED
    assert classify_variant({}, "English SDH") is SubtitleVariant.SDH
    assert classify_variant({}, "English (Hearing Impaired)") is SubtitleVariant.SDH
    assert classify_variant({}, "Closed Captions") is SubtitleVariant.SDH
    assert classify_variant({}, "English CC") is SubtitleVariant.SDH


def test_conflicting_title_labels_are_unknown() -> None:
    assert classify_variant({}, "Forced SDH") is SubtitleVariant.UNKNOWN


def test_short_title_tokens_use_word_boundaries() -> None:
    # A stray "cc" inside another word must not be read as a closed-caption label.
    assert classify_variant({}, "Soccer commentary") is SubtitleVariant.NORMAL
    # And "forced" only as a whole word.
    assert classify_variant({}, "Reinforced edition") is SubtitleVariant.NORMAL


def test_string_disposition_values_are_honoured() -> None:
    # ffprobe reports flags as integers, but accept the stringy form defensively.
    assert classify_variant({"forced": "1"}, None) is SubtitleVariant.FORCED


def test_variant_flag_mapping() -> None:
    assert SubtitleVariant.NORMAL.flag is None
    assert SubtitleVariant.UNKNOWN.flag is None
    assert SubtitleVariant.FORCED.flag == "forced"
    assert SubtitleVariant.SDH.flag == "sdh"
