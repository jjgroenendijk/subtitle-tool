"""Tests for the Plex filename-normalisation step."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.steps.naming import normalize_filename
from subtitle_tool.pipeline.workitem import WorkItem


def _item(name: str, video_stem: str | None, converted: bool = False) -> WorkItem:
    path = Path(name)
    return WorkItem(source=path, target=path, text="", video_stem=video_stem, converted=converted)


def test_already_normalized_name_is_unchanged() -> None:
    item = _item("Movie (2020).en.srt", "Movie (2020)")
    normalize_filename(item, Config())
    assert item.target == Path("Movie (2020).en.srt")
    assert item.actions == []
    assert not item.remove_source


def test_subtitle_renamed_to_video_basename() -> None:
    item = _item("Show.1x01.en.srt", "Show - S01E01 - Pilot")
    normalize_filename(item, Config())
    assert item.target == Path("Show - S01E01 - Pilot.en.srt")
    assert [a.type for a in item.actions] == [ActionType.RENAME]
    # A pure rename moves the file, so the old name is removed.
    assert item.remove_source


def test_flag_synonyms_are_standardized() -> None:
    item = _item("Movie (2020).en.hi.srt", "Movie (2020)")
    normalize_filename(item, Config())
    assert item.target == Path("Movie (2020).en.sdh.srt")


def test_forced_and_sdh_order_is_fixed() -> None:
    item = _item("Movie (2020).en.cc.forced.srt", "Movie (2020)")
    normalize_filename(item, Config())
    assert item.target == Path("Movie (2020).en.forced.sdh.srt")


def test_converted_file_does_not_flag_source_removal() -> None:
    # After a conversion the source is a different file; renaming the planned target
    # must not mark the original for removal (the conversion step owns that choice).
    item = _item("Movie (2020).fr.srt", "Movie (2020)", converted=True)
    item.source = Path("Movie (2020).french.ass")
    normalize_filename(item, Config())
    assert not item.remove_source


def test_unrecognized_name_without_language_is_left_with_warning() -> None:
    item = _item("Completely Different.srt", "Movie (2020)")
    normalize_filename(item, Config())
    assert item.target == Path("Completely Different.srt")
    assert item.actions == []
    assert item.warnings


def test_standalone_subtitle_standardizes_its_own_flags() -> None:
    item = _item("Movie (2020).en.hi.srt", None)
    normalize_filename(item, Config())
    assert item.target == Path("Movie (2020).en.sdh.srt")
    assert [a.type for a in item.actions] == [ActionType.RENAME]
