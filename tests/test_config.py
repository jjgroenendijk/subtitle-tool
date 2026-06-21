"""Tests for loading and validating the persisted config file."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from subtitle_tool.config import Config, ConfigError, FilterAction, load_config
from subtitle_tool.config.models import FilterAction as FilterActionModel

if TYPE_CHECKING:
    from pathlib import Path


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_empty_file_yields_default_config(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, ""))

    assert config == Config()
    # Conservative defaults: destructive options off.
    assert config.extraction.enabled is False
    assert config.extraction.remux is False
    assert config.extraction.delete_original_video is False
    assert config.format.delete_original_after_conversion is False
    assert config.language.filter.enabled is False
    assert config.cleanup.strip_styling is False
    # Sensible non-destructive defaults on.
    assert config.format.convert_to_utf8 is True
    assert config.watcher.enabled is True


def test_loads_a_full_valid_config(tmp_path: Path) -> None:
    body = """
    [scan]
    media_paths = ["/media/movies", "/media/tv"]
    exclude_patterns = ["**/sample/**"]
    interval_hours = 12
    scan_on_startup = true

    [watcher]
    enabled = false
    stability_window_seconds = 60

    [extraction]
    enabled = true
    languages = ["en", "nl"]
    remux = true
    delete_original_video = true

    [format]
    convert_to_srt = true
    delete_original_after_conversion = true

    [language]
    min_confidence = 0.9

    [language.filter]
    enabled = true
    wanted_languages = ["en", "nl"]
    action = "delete"

    [cleanup]
    strip_styling = true

    [history]
    retention_limit = 50
    """
    config = load_config(write_config(tmp_path, body))

    assert config.scan.media_paths == ["/media/movies", "/media/tv"]
    assert config.scan.interval_hours == 12
    assert config.extraction.languages == ["en", "nl"]
    assert config.language.filter.action is FilterAction.DELETE
    assert config.history.retention_limit == 50
    assert FilterAction is FilterActionModel


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "does-not-exist.toml")


def test_malformed_toml_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write_config(tmp_path, "this is = = not toml"))


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"scan\.nonsense"):
        load_config(write_config(tmp_path, "[scan]\nnonsense = 1\n"))


def test_out_of_range_value_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"language\.min_confidence"):
        load_config(write_config(tmp_path, "[language]\nmin_confidence = 2.0\n"))


def test_non_positive_interval_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"scan\.interval_hours"):
        load_config(write_config(tmp_path, "[scan]\ninterval_hours = 0\n"))


def test_invalid_language_code_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="ISO 639-1"):
        load_config(write_config(tmp_path, '[extraction]\nlanguages = ["eng"]\n'))


def test_stream_variant_actions_default_to_compatible_behavior() -> None:
    from subtitle_tool.config.models import StreamAction

    extraction = Config().extraction
    # Normal/forced/sdh keep today's broad extraction; unknown stays embedded.
    assert extraction.normal is StreamAction.EXTRACT
    assert extraction.forced is StreamAction.EXTRACT
    assert extraction.sdh is StreamAction.EXTRACT
    assert extraction.unknown is StreamAction.KEEP_EMBEDDED


def test_stream_variant_actions_load_from_config(tmp_path: Path) -> None:
    from subtitle_tool.config.models import StreamAction

    body = (
        "[extraction]\nenabled = true\n"
        'forced = "keep_embedded"\nsdh = "keep_embedded"\nunknown = "extract"\n'
    )
    config = load_config(write_config(tmp_path, body))

    assert config.extraction.forced is StreamAction.KEEP_EMBEDDED
    assert config.extraction.sdh is StreamAction.KEEP_EMBEDDED
    assert config.extraction.unknown is StreamAction.EXTRACT
    assert config.extraction.normal is StreamAction.EXTRACT


def test_invalid_stream_action_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"extraction\.forced"):
        load_config(write_config(tmp_path, '[extraction]\nforced = "drop"\n'))


def test_selection_defaults_keep_all_variants() -> None:
    from subtitle_tool.config.models import SelectionMode

    extraction = Config().extraction
    assert extraction.selection_mode is SelectionMode.ALL
    assert extraction.preference_order == ["normal", "sdh", "forced"]


def test_selection_mode_and_preference_load_from_config(tmp_path: Path) -> None:
    from subtitle_tool.config.models import SelectionMode

    body = (
        "[extraction]\nenabled = true\n"
        'selection_mode = "one_per_language"\npreference_order = ["normal", "sdh"]\n'
    )
    config = load_config(write_config(tmp_path, body))

    assert config.extraction.selection_mode is SelectionMode.ONE_PER_LANGUAGE
    assert config.extraction.preference_order == ["normal", "sdh"]


def test_invalid_selection_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"extraction\.selection_mode"):
        load_config(write_config(tmp_path, '[extraction]\nselection_mode = "best"\n'))


def test_unknown_preference_variant_is_rejected(tmp_path: Path) -> None:
    body = '[extraction]\npreference_order = ["normal", "dubbed"]\n'
    with pytest.raises(ConfigError, match="preference_order"):
        load_config(write_config(tmp_path, body))


def test_duplicate_preference_variant_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="more than once"):
        load_config(
            write_config(tmp_path, '[extraction]\npreference_order = ["normal", "normal"]\n')
        )


def test_preference_variant_names_match_classifier() -> None:
    # The config's variant name list mirrors the pipeline's SubtitleVariant enum; this
    # guards against the two drifting apart.
    from subtitle_tool.config.models import _VARIANT_NAMES
    from subtitle_tool.pipeline.stream_variants import SubtitleVariant

    assert set(_VARIANT_NAMES) == {v.value for v in SubtitleVariant}


def test_delete_video_without_remux_is_rejected(tmp_path: Path) -> None:
    body = "[extraction]\nenabled = true\nremux = false\ndelete_original_video = true\n"
    with pytest.raises(ConfigError, match=r"requires extraction\.remux"):
        load_config(write_config(tmp_path, body))


def test_delete_after_conversion_without_conversion_is_rejected(tmp_path: Path) -> None:
    body = "[format]\nconvert_to_srt = false\ndelete_original_after_conversion = true\n"
    with pytest.raises(ConfigError, match=r"requires format\.convert_to_srt"):
        load_config(write_config(tmp_path, body))


def test_filtering_without_languages_is_rejected(tmp_path: Path) -> None:
    body = "[language.filter]\nenabled = true\nwanted_languages = []\n"
    with pytest.raises(ConfigError, match="at least one code"):
        load_config(write_config(tmp_path, body))


def test_dump_config_round_trips(tmp_path: Path) -> None:
    from subtitle_tool.config import dump_config

    original = load_config(write_config(tmp_path, '[scan]\nmedia_paths = ["/media"]\n'))
    dumped = dump_config(original)

    assert Config.model_validate(dumped) == original


def test_save_config_round_trips_through_the_file(tmp_path: Path) -> None:
    from subtitle_tool.config import save_config

    original = load_config(write_config(tmp_path, FULL_CONFIG_BODY))
    path = tmp_path / "written.toml"

    save_config(original, path)

    assert load_config(path) == original


def test_save_config_writes_atomically_and_creates_parent(tmp_path: Path) -> None:
    from subtitle_tool.config import save_config

    path = tmp_path / "nested" / "config.toml"

    save_config(Config(), path)

    assert path.exists()
    # No temporary files left behind by the atomic write.
    assert list(path.parent.glob(".*")) == []
    assert load_config(path) == Config()


FULL_CONFIG_BODY = """
[scan]
media_paths = ["/media/movies", "/media/tv"]
interval_hours = 12

[language.filter]
enabled = true
wanted_languages = ["en", "nl"]
action = "delete"
"""
