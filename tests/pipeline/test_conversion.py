"""Tests for the ASS/SSA/VTT to SRT conversion step."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.steps.conversion import convert_format
from subtitle_tool.pipeline.workitem import WorkItem

ASS = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello {\\i1}world{\\i0}\n"
)
VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello world\n"


def _item(source: Path, text: str) -> WorkItem:
    return WorkItem(source=source, target=source, text=text)


def test_ass_is_converted_to_srt(tmp_path: Path) -> None:
    source = tmp_path / "Movie.ass"
    item = _item(source, ASS)
    convert_format(item, Config())
    assert item.target == tmp_path / "Movie.srt"
    assert item.converted
    assert "00:00:01,000 --> 00:00:03,000" in item.text
    assert "<i>world</i>" in item.text
    assert [action.type for action in item.actions] == [ActionType.CONVERT_FORMAT]
    assert not item.remove_source


def test_vtt_is_converted_to_srt(tmp_path: Path) -> None:
    source = tmp_path / "Movie.vtt"
    item = _item(source, VTT)
    convert_format(item, Config())
    assert item.target == tmp_path / "Movie.srt"
    assert "-->" in item.text


def test_srt_input_is_left_untouched(tmp_path: Path) -> None:
    source = tmp_path / "Movie.srt"
    item = _item(source, "1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    convert_format(item, Config())
    assert item.target == source
    assert not item.converted
    assert item.actions == []


def test_conversion_disabled_is_a_noop(tmp_path: Path) -> None:
    config = Config.model_validate({"format": {"convert_to_srt": False}})
    item = _item(tmp_path / "Movie.ass", ASS)
    convert_format(item, config)
    assert item.actions == []
    assert not item.converted


def test_delete_original_records_action_and_flags_removal(tmp_path: Path) -> None:
    config = Config.model_validate(
        {"format": {"convert_to_srt": True, "delete_original_after_conversion": True}}
    )
    item = _item(tmp_path / "Movie.ass", ASS)
    convert_format(item, config)
    assert item.remove_source
    assert {action.type for action in item.actions} == {
        ActionType.CONVERT_FORMAT,
        ActionType.DELETE_ORIGINAL,
    }


def test_broken_input_warns_and_leaves_content(tmp_path: Path) -> None:
    source = tmp_path / "Movie.vtt"
    # Missing the WEBVTT header makes pysubs2 reject the VTT input.
    item = _item(source, "this is not a valid vtt file at all")
    convert_format(item, Config())
    assert item.actions == []
    assert item.warnings
    assert item.target == source


def test_existing_converted_target_skips_to_stay_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "Movie.ass"
    (tmp_path / "Movie.srt").write_text("already converted", encoding="utf-8")
    item = _item(source, ASS)
    convert_format(item, Config())
    assert item.actions == []
    assert not item.converted
    assert item.target == source
