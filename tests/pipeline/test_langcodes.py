"""Tests for the ISO 639-2 to 639-1 language-code mapping."""

from __future__ import annotations

from subtitle_tool.pipeline.langcodes import iso639_2_to_1


def test_maps_terminologic_and_bibliographic_variants() -> None:
    # Both 639-2 spellings of the same language resolve to one 639-1 code.
    assert iso639_2_to_1("deu") == "de"
    assert iso639_2_to_1("ger") == "de"
    assert iso639_2_to_1("fre") == "fr"
    assert iso639_2_to_1("fra") == "fr"
    assert iso639_2_to_1("dut") == "nl"
    assert iso639_2_to_1("nld") == "nl"
    assert iso639_2_to_1("cze") == "cs"
    assert iso639_2_to_1("ces") == "cs"


def test_maps_common_single_form_codes() -> None:
    assert iso639_2_to_1("eng") == "en"
    assert iso639_2_to_1("jpn") == "ja"
    assert iso639_2_to_1("nob") == "nb"


def test_lookup_is_case_insensitive() -> None:
    assert iso639_2_to_1("ENG") == "en"
    assert iso639_2_to_1(" Eng ") == "en"


def test_unknown_and_empty_codes_return_none() -> None:
    assert iso639_2_to_1(None) is None
    assert iso639_2_to_1("") is None
    assert iso639_2_to_1("und") is None
    assert iso639_2_to_1("xyz") is None


def test_language_without_iso_639_1_form_returns_none() -> None:
    # Registered 639-2 codes that have no two-letter form degrade to None rather
    # than raising, so the extracted subtitle simply carries no language token.
    assert iso639_2_to_1("fil") is None
    assert iso639_2_to_1("zxx") is None
