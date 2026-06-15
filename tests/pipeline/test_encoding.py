"""Tests for the encoding-detection-and-UTF-8 step."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.steps.encoding import normalize_encoding
from subtitle_tool.pipeline.workitem import WorkItem

CYRILLIC = "Привет мир, это субтитры на русском языке для проверки кодировки."


def _item(name: str = "sub.srt") -> WorkItem:
    path = Path(name)
    return WorkItem(source=path, target=path, text="")


def test_already_utf8_file_decodes_without_action() -> None:
    item = _item()
    normalize_encoding(item, Config(), "Héllo wörld\n".encode())
    assert item.text == "Héllo wörld\n"
    assert item.actions == []


def test_ascii_file_decodes_without_action() -> None:
    item = _item()
    normalize_encoding(item, Config(), b"plain ascii\n")
    assert item.text == "plain ascii\n"
    assert item.actions == []


def test_non_utf8_file_is_converted_and_records_action() -> None:
    item = _item()
    normalize_encoding(item, Config(), CYRILLIC.encode("windows-1251"))
    assert item.text == CYRILLIC
    assert [action.type for action in item.actions] == [ActionType.CONVERT_ENCODING]


def test_conversion_disabled_decodes_but_records_no_action() -> None:
    config = Config.model_validate({"format": {"convert_to_utf8": False}})
    item = _item()
    normalize_encoding(item, config, CYRILLIC.encode("windows-1251"))
    assert item.text == CYRILLIC
    assert item.actions == []


def test_conversion_disabled_remembers_original_encoding() -> None:
    config = Config.model_validate({"format": {"convert_to_utf8": False}})
    item = _item()
    normalize_encoding(item, config, CYRILLIC.encode("windows-1251"))
    # The commit must re-encode with the original encoding, never UTF-8.
    assert item.output_encoding != "utf-8"
    assert item.text.encode(item.output_encoding) == CYRILLIC.encode("windows-1251")


def test_conversion_disabled_keeps_utf8_for_utf8_input() -> None:
    config = Config.model_validate({"format": {"convert_to_utf8": False}})
    item = _item()
    normalize_encoding(item, config, "Héllo wörld\n".encode())
    # An already-UTF-8 file round-trips losslessly as UTF-8.
    assert item.output_encoding == "utf-8"


def test_empty_file_decodes_to_empty_text_without_error() -> None:
    item = _item()
    normalize_encoding(item, Config(), b"")
    assert item.text == ""
    assert item.actions == []
