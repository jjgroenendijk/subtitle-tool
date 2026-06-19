"""Tests for the worker reporting helpers: counters, mapping, and event payloads."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.jobs.reporting import (
    Counters,
    count_to_process,
    file_event,
    to_job_file,
)
from subtitle_tool.pipeline.models import Action, ActionType, FileResult
from subtitle_tool.scanner.models import ScanResult, StandaloneSubtitle, VideoGroup


def _result(**kwargs: object) -> FileResult:
    defaults: dict[str, object] = {"source": Path("a.srt"), "target": Path("a.en.srt")}
    defaults.update(kwargs)
    return FileResult(**defaults)  # type: ignore[arg-type]


def test_record_file_counts_applied_change_in_real_run() -> None:
    counters = Counters()
    rename = Action(ActionType.RENAME, "rename")

    counters.record_file(_result(actions=[rename], applied=True), dry_run=False)

    assert counters.processed == 1
    assert counters.changed == 1
    assert counters.total == 1


def test_record_file_skips_unapplied_change_in_real_run() -> None:
    counters = Counters()
    rename = Action(ActionType.RENAME, "rename")

    # Planned but not written (validation rejected): processed but not a change.
    counters.record_file(_result(actions=[rename], applied=False), dry_run=False)

    assert counters.processed == 1
    assert counters.changed == 0


def test_record_file_counts_planned_change_in_dry_run() -> None:
    counters = Counters()
    rename = Action(ActionType.RENAME, "rename")

    counters.record_file(_result(actions=[rename], applied=False), dry_run=True)

    assert counters.changed == 1


def test_record_file_tallies_errors_warnings_and_unwanted() -> None:
    counters = Counters()
    delete = Action(ActionType.DELETE_FILTERED, "filtered")

    counters.record_file(_result(error="boom"), dry_run=False)
    counters.record_file(_result(warnings=["w1", "w2"]), dry_run=False)
    counters.record_file(_result(actions=[delete], applied=True), dry_run=False)

    assert counters.errors == 1
    assert counters.warnings == 2
    assert counters.unwanted == 1
    assert counters.processed == 3


def test_record_file_unwanted_needs_applied_in_real_run() -> None:
    counters = Counters()
    delete = Action(ActionType.DELETE_FILTERED, "filtered")

    # A filtered delete that was not applied is not counted as removed.
    counters.record_file(_result(actions=[delete], applied=False), dry_run=False)

    assert counters.unwanted == 0


def test_record_file_total_never_trails_processed() -> None:
    counters = Counters(total=0)

    counters.record_file(_result(), dry_run=False)
    counters.record_file(_result(), dry_run=False)

    assert counters.total == 2


def test_count_to_process_without_index_counts_all_subtitles() -> None:
    scan_result = ScanResult(
        video_groups=[VideoGroup(video=Path("m.mkv"), subtitles=[Path("m.en.srt")])],
        standalone_subtitles=[StandaloneSubtitle(subtitle=Path("x.srt"), warnings=[])],
    )

    assert count_to_process(scan_result, None) == scan_result.subtitle_count


def test_count_to_process_counts_only_paths_in_scope() -> None:
    grouped = Path("m.en.srt")
    standalone = Path("x.srt")
    scan_result = ScanResult(
        video_groups=[VideoGroup(video=Path("m.mkv"), subtitles=[grouped, Path("m.nl.srt")])],
        standalone_subtitles=[StandaloneSubtitle(subtitle=standalone, warnings=[])],
    )

    assert count_to_process(scan_result, {grouped, standalone}) == 2


def test_to_job_file_maps_actions_and_fields() -> None:
    result = _result(
        actions=[Action(ActionType.RENAME, "rename it")],
        warnings=["careful"],
        error=None,
    )

    job_file = to_job_file(result)

    assert job_file.source == "a.srt"
    assert job_file.target == "a.en.srt"
    assert job_file.actions == [("rename", "rename it")]
    assert job_file.warnings == ["careful"]


def test_file_event_shapes_payload() -> None:
    job_file = to_job_file(_result(actions=[Action(ActionType.RENAME, "rename it")]))

    event = file_event(job_file)

    assert event["source"] == "a.srt"
    assert event["target"] == "a.en.srt"
    assert event["changed"] is True
    assert event["actions"] == [["rename", "rename it"]]
