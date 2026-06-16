"""Tests for the tolerant SRT block parser and serialiser."""

from __future__ import annotations

from subtitle_tool.pipeline.srt import compose_srt, parse_srt

GOOD = (
    "1\n00:00:01,000 --> 00:00:04,000\nHello there\n\n"
    "2\n00:00:05,000 --> 00:00:07,000\nLine one\nLine two\n"
)


def test_parse_good_file_yields_cues_with_timing_and_text() -> None:
    blocks = parse_srt(GOOD)
    assert len(blocks) == 2
    assert blocks[0].timing == "00:00:01,000 --> 00:00:04,000"
    assert blocks[0].lines == ["Hello there"]
    assert blocks[1].lines == ["Line one", "Line two"]
    assert not any(block.is_broken for block in blocks)


def test_parse_handles_crlf_and_bom() -> None:
    text = "﻿1\r\n00:00:01,000 --> 00:00:04,000\r\nHi\r\n"
    blocks = parse_srt(text)
    assert len(blocks) == 1
    assert blocks[0].timing == "00:00:01,000 --> 00:00:04,000"
    assert blocks[0].lines == ["Hi"]


def test_block_with_no_timing_is_broken() -> None:
    blocks = parse_srt("1\njust some text with no timing\n")
    assert len(blocks) == 1
    assert blocks[0].is_broken
    assert blocks[0].lines == ["1", "just some text with no timing"]


def test_block_with_timing_but_no_text_is_empty() -> None:
    blocks = parse_srt("1\n00:00:01,000 --> 00:00:04,000\n")
    assert len(blocks) == 1
    assert not blocks[0].is_broken
    assert blocks[0].is_empty


def test_compose_renumbers_from_one() -> None:
    blocks = parse_srt(
        "7\n00:00:01,000 --> 00:00:04,000\nA\n\n9\n00:00:05,000 --> 00:00:07,000\nB\n"
    )
    composed = compose_srt(blocks)
    assert composed == (
        "1\n00:00:01,000 --> 00:00:04,000\nA\n\n2\n00:00:05,000 --> 00:00:07,000\nB\n"
    )


def test_parse_compose_roundtrip_is_stable_for_clean_input() -> None:
    once = compose_srt(parse_srt(GOOD))
    twice = compose_srt(parse_srt(once))
    assert once == twice


def test_compose_empty_blocks_yields_empty_string() -> None:
    assert compose_srt([]) == ""


def test_broken_block_is_preserved_through_compose() -> None:
    # A chunk with no timing line survives a parse/compose round-trip as a broken
    # block so the cleanup step, not the parser, decides whether to drop it.
    blocks = parse_srt(
        "1\n00:00:01,000 --> 00:00:04,000\nKeep\n\n2\nno timing here\nstill broken\n"
    )
    assert [block.is_broken for block in blocks] == [False, True]
    composed = compose_srt(blocks)
    assert composed == (
        "1\n00:00:01,000 --> 00:00:04,000\nKeep\n\n2\n2\nno timing here\nstill broken\n"
    )


def test_period_millisecond_separator_is_accepted() -> None:
    blocks = parse_srt("1\n00:00:01.000 --> 00:00:04.000\nHi\n")
    assert len(blocks) == 1
    assert not blocks[0].is_broken
    # Normalised back to the SRT comma separator on the timing line.
    assert blocks[0].timing == "00:00:01,000 --> 00:00:04,000"


def test_two_cues_without_blank_separator_are_both_kept() -> None:
    # A missing blank separator must not cost dialogue: both cues survive rather than
    # collapsing into one broken block that cleanup would drop.
    blocks = parse_srt(
        "1\n00:00:01,000 --> 00:00:02,000\nFirst\n2\n00:00:03,000 --> 00:00:04,000\nSecond\n"
    )
    assert [block.text for block in blocks] == ["First", "Second"]
    assert not any(block.is_broken for block in blocks)


def test_cue_with_leading_junk_before_timing_is_recovered() -> None:
    # A stray duplicate index ahead of the timing line is skipped, not treated as a
    # broken block, so the cue text is preserved through cleanup.
    blocks = parse_srt("7\n7\n00:00:01,000 --> 00:00:04,000\nKeep\n")
    assert len(blocks) == 1
    assert not blocks[0].is_broken
    assert blocks[0].text == "Keep"


def test_positioning_metadata_survives_round_trip() -> None:
    text = "1\n00:00:01,000 --> 00:00:04,000 X1:100 X2:200 Y1:1 Y2:2\nHi\n"
    composed = compose_srt(parse_srt(text))
    assert "X1:100 X2:200 Y1:1 Y2:2" in composed
