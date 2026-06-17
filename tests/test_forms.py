"""Tests for deriving the config form: field specs, language/path widgets, parsing."""

from __future__ import annotations

from subtitle_tool.config.languages import language_choices
from subtitle_tool.web import forms


def spec_by_name(name: str) -> forms.FieldSpec:
    return next(spec for spec in forms.field_specs() if spec.name == name)


def test_language_fields_become_predefined_choices() -> None:
    for name in ("extraction.languages", "language.filter.wanted_languages"):
        spec = spec_by_name(name)
        assert spec.kind == "languages"
        # Choices carry a bare code value and a readable label.
        english = next(choice for choice in spec.choices if choice.value == "en")
        assert english.label == "English (en)"


def test_media_paths_becomes_a_path_picker() -> None:
    spec = spec_by_name("scan.media_paths")
    assert spec.kind == "paths"


def test_plain_list_field_stays_a_textarea_list() -> None:
    spec = spec_by_name("scan.exclude_patterns")
    assert spec.kind == "list"


def test_enum_choices_use_value_and_label() -> None:
    spec = spec_by_name("language.filter.action")
    assert spec.kind == "enum"
    assert {choice.value for choice in spec.choices} == {"warn", "delete"}
    assert all(choice.value == choice.label for choice in spec.choices)


def test_language_choices_are_sorted_by_name() -> None:
    labels = [label for _, label in language_choices()]
    assert labels == sorted(labels)
    codes = [code for code, _ in language_choices()]
    assert "en" in codes
    assert "nl" in codes


def test_parse_reads_multiselect_language_values() -> None:
    specs = forms.field_specs()
    parsed = forms.parse({"language.filter.wanted_languages": ["en", "nl"]}, specs)
    assert parsed["language"]["filter"]["wanted_languages"] == ["en", "nl"]


def test_parse_reads_a_single_language_value() -> None:
    specs = forms.field_specs()
    parsed = forms.parse({"extraction.languages": "fr"}, specs)
    assert parsed["extraction"]["languages"] == ["fr"]


def test_parse_reads_paths_from_a_newline_textarea() -> None:
    specs = forms.field_specs()
    parsed = forms.parse({"scan.media_paths": "/media/movies\n/media/tv\n"}, specs)
    assert parsed["scan"]["media_paths"] == ["/media/movies", "/media/tv"]
