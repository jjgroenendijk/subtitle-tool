"""Tests for the end-to-end scan against temporary directory trees."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.scanner.models import WarningReason
from subtitle_tool.scanner.scanner import scan, scan_paths


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_scan_pairs_subtitle_variants_with_video(tmp_path: Path) -> None:
    _touch(tmp_path / "Movie (2020).mkv")
    _touch(tmp_path / "Movie (2020).en.srt")
    _touch(tmp_path / "Movie (2020).en.sdh.srt")
    _touch(tmp_path / "Movie (2020).nl.forced.srt")

    result = scan_paths([str(tmp_path)], [])

    assert len(result.video_groups) == 1
    group = result.video_groups[0]
    assert group.video == tmp_path / "Movie (2020).mkv"
    assert group.subtitles == [
        tmp_path / "Movie (2020).en.sdh.srt",
        tmp_path / "Movie (2020).en.srt",
        tmp_path / "Movie (2020).nl.forced.srt",
    ]
    assert result.standalone_subtitles == []
    assert result.warnings == []


def test_video_without_subtitle_is_a_group_with_no_subtitles(tmp_path: Path) -> None:
    _touch(tmp_path / "Lonely (2021).mkv")

    result = scan_paths([str(tmp_path)], [])

    assert len(result.video_groups) == 1
    assert result.video_groups[0].subtitles == []


def test_unmatched_subtitle_is_standalone_with_no_match_warning(tmp_path: Path) -> None:
    _touch(tmp_path / "Movie (2020).mkv")
    _touch(tmp_path / "Something Else.en.srt")

    result = scan_paths([str(tmp_path)], [])

    assert result.video_groups[0].subtitles == []
    assert len(result.standalone_subtitles) == 1
    standalone = result.standalone_subtitles[0]
    assert standalone.subtitle == tmp_path / "Something Else.en.srt"
    assert [w.reason for w in standalone.warnings] == [WarningReason.NO_MATCH]


def test_ambiguous_subtitle_is_standalone_with_ambiguous_warning(tmp_path: Path) -> None:
    _touch(tmp_path / "Movie (2020).mkv")
    _touch(tmp_path / "Movie (2020).mp4")
    _touch(tmp_path / "Movie (2020).en.srt")

    result = scan_paths([str(tmp_path)], [])

    assert len(result.standalone_subtitles) == 1
    standalone = result.standalone_subtitles[0]
    assert [w.reason for w in standalone.warnings] == [WarningReason.AMBIGUOUS_MATCH]
    # Neither video claimed the subtitle.
    assert all(group.subtitles == [] for group in result.video_groups)


def test_episode_matching_within_a_season_folder(tmp_path: Path) -> None:
    season = tmp_path / "Show" / "Season 01"
    _touch(season / "Show - S01E01 - Pilot.mkv")
    _touch(season / "Show - S01E02 - Next.mkv")
    _touch(season / "Show.1x01.en.srt")
    _touch(season / "Show.1x02.en.srt")

    result = scan_paths([str(tmp_path)], [])

    groups = {g.video.name: g.subtitles for g in result.video_groups}
    assert groups["Show - S01E01 - Pilot.mkv"] == [season / "Show.1x01.en.srt"]
    assert groups["Show - S01E02 - Next.mkv"] == [season / "Show.1x02.en.srt"]
    assert result.standalone_subtitles == []


def test_matching_is_scoped_per_directory(tmp_path: Path) -> None:
    _touch(tmp_path / "a" / "Movie (2020).mkv")
    _touch(tmp_path / "b" / "Movie (2020).en.srt")

    result = scan_paths([str(tmp_path)], [])

    # The subtitle in b/ does not reach across to the video in a/.
    assert len(result.standalone_subtitles) == 1
    assert result.standalone_subtitles[0].subtitle == tmp_path / "b" / "Movie (2020).en.srt"


def test_exclude_pattern_keeps_directory_out_of_scan(tmp_path: Path) -> None:
    _touch(tmp_path / "Movie (2020).mkv")
    _touch(tmp_path / "Sample" / "Movie (2020).en.srt")

    result = scan_paths([str(tmp_path)], ["Sample"])

    assert result.standalone_subtitles == []
    assert result.video_groups[0].subtitles == []


def test_scan_uses_config_paths(tmp_path: Path) -> None:
    _touch(tmp_path / "Movie (2020).mkv")
    _touch(tmp_path / "Movie (2020).en.srt")
    config = Config.model_validate({"scan": {"media_paths": [str(tmp_path)]}})

    result = scan(config)

    assert result.video_groups[0].subtitles == [tmp_path / "Movie (2020).en.srt"]


def test_overlapping_roots_do_not_double_count(tmp_path: Path) -> None:
    _touch(tmp_path / "Movie (2020).mkv")
    _touch(tmp_path / "Movie (2020).en.srt")

    result = scan_paths([str(tmp_path), str(tmp_path)], [])

    assert len(result.video_groups) == 1
    assert result.video_groups[0].subtitles == [tmp_path / "Movie (2020).en.srt"]
