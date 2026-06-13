"""Tests for the content-cleanup step and its individually toggleable rules."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.srt import parse_srt
from subtitle_tool.pipeline.steps.cleanup import clean
from subtitle_tool.pipeline.workitem import WorkItem


def _item(text: str) -> WorkItem:
    path = Path("Movie.en.srt")
    return WorkItem(source=path, target=path, text=text)


def _texts(item: WorkItem) -> list[str]:
    return [block.text for block in parse_srt(item.text)]


def test_clean_file_produces_no_actions() -> None:
    item = _item(
        "1\n00:00:01,000 --> 00:00:04,000\nHello\n\n2\n00:00:05,000 --> 00:00:07,000\nWorld\n"
    )
    before = item.text
    clean(item, Config())
    assert item.actions == []
    assert item.text == before


def test_ad_lines_are_removed_and_ad_only_block_dropped() -> None:
    item = _item(
        "1\n00:00:01,000 --> 00:00:04,000\nReal line\nSubtitles by OpenSubtitles\n\n"
        "2\n00:00:05,000 --> 00:00:07,000\nDownloaded from www.example.com\n"
    )
    clean(item, Config())
    assert _texts(item) == ["Real line"]
    assert any(a.type is ActionType.CLEANUP for a in item.actions)


def test_empty_and_broken_blocks_are_removed() -> None:
    item = _item(
        "1\n00:00:01,000 --> 00:00:04,000\nKeep\n\n"
        "2\n00:00:05,000 --> 00:00:07,000\n\n\n"
        "3\nbroken block with no timing\n"
    )
    clean(item, Config())
    assert _texts(item) == ["Keep"]


def test_consecutive_duplicate_blocks_are_collapsed() -> None:
    item = _item(
        "1\n00:00:01,000 --> 00:00:04,000\nSame\n\n"
        "2\n00:00:05,000 --> 00:00:07,000\nSame\n\n"
        "3\n00:00:08,000 --> 00:00:09,000\nDifferent\n"
    )
    clean(item, Config())
    assert _texts(item) == ["Same", "Different"]


def test_artifact_lines_are_removed() -> None:
    item = _item(
        "1\n00:00:01,000 --> 00:00:04,000\n♪\n\n2\n00:00:05,000 --> 00:00:07,000\nReal\n-\n"
    )
    clean(item, Config())
    assert _texts(item) == ["Real"]


def test_styling_kept_by_default_stripped_when_enabled() -> None:
    text = "1\n00:00:01,000 --> 00:00:04,000\n<i>Italic</i> {\\an8}top\n"
    kept = _item(text)
    clean(kept, Config())
    assert "<i>" in kept.text

    config = Config.model_validate({"cleanup": {"strip_styling": True}})
    stripped = _item(text)
    clean(stripped, config)
    assert "<i>" not in stripped.text
    assert "{\\an8}" not in stripped.text
    assert "Italic top" in stripped.text


def test_individual_rule_toggle_disables_only_that_rule() -> None:
    config = Config.model_validate({"cleanup": {"remove_duplicate_blocks": False}})
    item = _item(
        "1\n00:00:01,000 --> 00:00:04,000\nSame\n\n2\n00:00:05,000 --> 00:00:07,000\nSame\n"
    )
    clean(item, config)
    # Duplicates kept because the rule is off; no other rule applies, so no change.
    assert _texts(item) == ["Same", "Same"]
    assert item.actions == []


def test_non_srt_target_is_left_untouched() -> None:
    path = Path("Movie.ass")
    item = WorkItem(source=path, target=path, text="not srt; has an ad www.example.com")
    clean(item, Config())
    assert item.actions == []
