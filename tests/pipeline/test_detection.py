"""Tests for the language-detection and filtering step.

Fixtures are short SRT documents in several languages plus a few awkward cases (a
file too short to detect, a mixed-language file, and a wrong code in the filename).
lingua is deterministic, so asserting on concrete detected codes is stable.
"""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.steps.detection import detect_language
from subtitle_tool.pipeline.workitem import WorkItem


def _srt(*lines: str) -> str:
    body = "\n\n".join(
        f"{i}\n00:00:0{i},000 --> 00:00:0{i + 1},000\n{line}" for i, line in enumerate(lines, 1)
    )
    return body + "\n"


ENGLISH = _srt(
    "Good morning, everyone. I hope you all slept well last night.",
    "We have a very long day ahead of us, so let us begin right away.",
)
FRENCH = _srt(
    "Bonjour tout le monde. J'espere que vous avez bien dormi cette nuit.",
    "Nous avons une tres longue journee devant nous, alors commencons tout de suite.",
)
GERMAN = _srt(
    "Guten Morgen, alle zusammen. Ich hoffe, ihr habt letzte Nacht gut geschlafen.",
    "Wir haben einen sehr langen Tag vor uns, also lasst uns gleich anfangen.",
)
DUTCH = _srt(
    "Goedemorgen allemaal. Ik hoop dat jullie vannacht goed geslapen hebben.",
    "We hebben een hele lange dag voor de boeg, dus laten we meteen beginnen.",
)
# Dominated by French; a balanced two-language file still resolves to one language.
MIXED = _srt(
    "Good morning everyone, I hope you slept well.",
    "Bonjour tout le monde, j'espere que vous avez bien dormi cette nuit.",
    "We have a long day, alors commencons tout de suite maintenant.",
)
SHORT = _srt("Oui.")


def _item(name: str, text: str) -> WorkItem:
    path = Path(name)
    return WorkItem(source=path, target=path, text=text)


def test_missing_code_is_filled_from_detection() -> None:
    item = _item("Movie (2020).srt", FRENCH)
    detect_language(item, Config())
    assert item.language == "fr"
    assert not item.warnings


def test_detection_agreeing_with_filename_keeps_code() -> None:
    item = _item("Movie (2020).de.srt", GERMAN)
    detect_language(item, Config())
    # Agreement: the decided code matches what is already there, so naming is a no-op.
    assert item.language == "de"
    assert not item.warnings
    assert item.actions == []


def test_wrong_code_in_filename_is_corrected_by_default() -> None:
    # File is named English but the content is Dutch; rename_to_detected defaults on.
    item = _item("Movie (2020).en.srt", DUTCH)
    detect_language(item, Config())
    assert item.language == "nl"


def test_wrong_code_kept_when_rename_disabled() -> None:
    item = _item("Movie (2020).en.srt", DUTCH)
    config = Config.model_validate({"language": {"rename_to_detected": False}})
    detect_language(item, config)
    assert item.language is None
    assert item.warnings


def test_short_file_is_inconclusive_and_left_untouched() -> None:
    item = _item("Movie (2020).srt", SHORT)
    detect_language(item, Config())
    assert item.language is None
    assert not item.delete_file
    assert item.warnings


def test_mixed_language_file_resolves_to_dominant_language() -> None:
    item = _item("Movie (2020).srt", MIXED)
    detect_language(item, Config())
    assert item.language == "fr"


def test_filter_deletes_unwanted_language() -> None:
    config = Config.model_validate(
        {"language": {"filter": {"enabled": True, "wanted_languages": ["en"], "action": "delete"}}}
    )
    item = _item("Movie (2020).fr.srt", FRENCH)
    detect_language(item, config)
    assert item.delete_file
    assert [a.type for a in item.actions] == [ActionType.DELETE_FILTERED]


def test_filter_warns_about_unwanted_language() -> None:
    config = Config.model_validate(
        {"language": {"filter": {"enabled": True, "wanted_languages": ["en"], "action": "warn"}}}
    )
    item = _item("Movie (2020).fr.srt", FRENCH)
    detect_language(item, config)
    assert not item.delete_file
    assert item.actions == []
    assert item.warnings


def test_filter_keeps_wanted_language() -> None:
    config = Config.model_validate(
        {"language": {"filter": {"enabled": True, "wanted_languages": ["en"], "action": "delete"}}}
    )
    item = _item("Movie (2020).en.srt", ENGLISH)
    detect_language(item, config)
    assert not item.delete_file
    assert item.actions == []
    assert not item.warnings


def test_low_confidence_skips_filtering() -> None:
    # Undetectable language is kept and warned, never filtered, even with delete on.
    config = Config.model_validate(
        {"language": {"filter": {"enabled": True, "wanted_languages": ["en"], "action": "delete"}}}
    )
    item = _item("Movie (2020).srt", SHORT)
    detect_language(item, config)
    assert not item.delete_file
    assert item.warnings
