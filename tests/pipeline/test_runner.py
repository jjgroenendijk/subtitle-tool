"""End-to-end pipeline tests over a fixture library in dry-run and real mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline import PipelineCancelled, ffmpeg, run_pipeline, sync
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.scanner import scan

ASS = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Bonjour le monde\n"
)
DIRTY_SRT = (
    "1\n00:00:01,000 --> 00:00:04,000\nReal dialogue\n\n"
    "2\n00:00:05,000 --> 00:00:07,000\nSubtitles by OpenSubtitles\n\n"
    "3\n00:00:08,000 --> 00:00:10,000\nEcho\n\n"
    "4\n00:00:10,500 --> 00:00:12,000\nEcho\n"
)
CLEAN_SRT = "1\n00:00:01,000 --> 00:00:04,000\nNothing to do here\n"
# Long enough for confident language detection in end-to-end tests.
DUTCH_SRT = (
    "1\n00:00:01,000 --> 00:00:04,000\n"
    "Goedemorgen allemaal. Ik hoop dat jullie vannacht goed geslapen hebben.\n\n"
    "2\n00:00:05,000 --> 00:00:08,000\n"
    "We hebben een hele lange dag voor de boeg, dus laten we meteen beginnen.\n"
)


def _build_library(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    # A non-UTF-8, ad-laden, duplicate-ridden SRT.
    (root / "Movie (2020).en.srt").write_bytes(DIRTY_SRT.encode("windows-1252"))
    # An ASS file to convert.
    (root / "Movie (2020).fr.ass").write_text(ASS, encoding="utf-8")
    # An already-clean, already-UTF-8 SRT that should be left alone.
    (root / "Other (2019).mkv").write_text("video", encoding="utf-8")
    (root / "Other (2019).en.srt").write_text(CLEAN_SRT, encoding="utf-8")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(root.iterdir())}


def _run(root: Path, *, dry_run: bool):
    config = Config.model_validate({"scan": {"media_paths": [str(root)]}})
    return run_pipeline(scan(config), config, dry_run=dry_run)


def test_dry_run_plans_changes_without_touching_files(tmp_path: Path) -> None:
    _build_library(tmp_path)
    before = _snapshot(tmp_path)

    result = _run(tmp_path, dry_run=True)

    assert result.dry_run
    assert _snapshot(tmp_path) == before  # nothing on disk changed
    changed = {r.source.name for r in result.changed_files}
    assert changed == {"Movie (2020).en.srt", "Movie (2020).fr.ass"}


def test_real_run_reaches_expected_end_state(tmp_path: Path) -> None:
    _build_library(tmp_path)

    _run(tmp_path, dry_run=False)

    names = sorted(p.name for p in tmp_path.iterdir())
    # The clean file is untouched; the ASS is converted (original kept by default);
    # the dirty SRT is cleaned in place.
    assert names == [
        "Movie (2020).en.srt",
        "Movie (2020).fr.ass",
        "Movie (2020).fr.srt",
        "Movie (2020).mkv",
        "Other (2019).en.srt",
        "Other (2019).mkv",
    ]

    cleaned = (tmp_path / "Movie (2020).en.srt").read_text(encoding="utf-8")
    assert "OpenSubtitles" not in cleaned  # ad removed
    assert cleaned.count("Echo") == 1  # duplicate collapsed
    assert "Real dialogue" in cleaned

    converted = (tmp_path / "Movie (2020).fr.srt").read_text(encoding="utf-8")
    assert "Bonjour le monde" in converted
    assert "-->" in converted

    # The already-clean file is byte-for-byte unchanged.
    assert (tmp_path / "Other (2019).en.srt").read_text(encoding="utf-8") == CLEAN_SRT


def test_cleanup_preserves_original_encoding_when_conversion_disabled(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    # A Windows-1252 SRT with an ad line: cleanup fires, but UTF-8 conversion is off.
    srt = (
        "1\n00:00:01,000 --> 00:00:04,000\nSubtitles by OpenSubtitles\nCafé\n\n"
        "2\n00:00:05,000 --> 00:00:07,000\nBonté divine\n"
    )
    path = tmp_path / "Movie (2020).fr.srt"
    path.write_bytes(srt.encode("windows-1252"))
    config = Config.model_validate(
        {
            "scan": {"media_paths": [str(tmp_path)]},
            "format": {"convert_to_utf8": False},
            "language": {"min_confidence": 1.0},
        }
    )

    result = run_pipeline(scan(config), config, dry_run=False)

    # The reported action is the cleanup; no encoding conversion is claimed.
    types = [a.type for r in result.file_results for a in r.actions]
    assert ActionType.CONVERT_ENCODING not in types
    assert ActionType.CLEANUP in types
    # The bytes stay Windows-1252: the ad line is gone, the accents are intact, and
    # the file is not silently transcoded to UTF-8.
    raw = path.read_bytes()
    assert b"OpenSubtitles" not in raw
    assert raw.decode("windows-1252") == (
        "1\n00:00:01,000 --> 00:00:04,000\nCafé\n\n2\n00:00:05,000 --> 00:00:07,000\nBonté divine\n"
    )
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")


def test_real_run_is_idempotent(tmp_path: Path) -> None:
    _build_library(tmp_path)
    _run(tmp_path, dry_run=False)
    after_first = _snapshot(tmp_path)

    second = _run(tmp_path, dry_run=False)

    assert second.changed_files == []
    assert _snapshot(tmp_path) == after_first


def test_validation_skipped_file_is_not_counted_as_changed(tmp_path: Path) -> None:
    # A subtitle whose only content is a broken block: cleanup decides to drop it,
    # which would leave an empty result, so the safety validator rejects the write
    # and the runner leaves the original untouched.
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    path = tmp_path / "Movie (2020).en.srt"
    broken = "this is a broken block with no timing\n"
    path.write_text(broken, encoding="utf-8")
    config = Config.model_validate(
        {"scan": {"media_paths": [str(tmp_path)]}, "language": {"min_confidence": 1.0}}
    )

    result = run_pipeline(scan(config), config, dry_run=False)

    # The file is on disk exactly as it was: no write happened.
    assert path.read_text(encoding="utf-8") == broken
    # The runner planned a cleanup but reports it skipped, not changed.
    assert result.changed_files == []
    assert [r.source.name for r in result.skipped_files] == ["Movie (2020).en.srt"]
    skipped = result.skipped_files[0]
    assert skipped.actions  # the planned cleanup is still reported
    assert not skipped.applied
    assert any("failed validation, left original untouched" in w for w in skipped.warnings)


def test_dry_run_reports_no_skipped_files(tmp_path: Path) -> None:
    # The same broken SRT in a dry run is reported as a planned change, never skipped:
    # a dry run writes nothing, so the validation that would reject it never runs.
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    path = tmp_path / "Movie (2020).en.srt"
    path.write_text("this is a broken block with no timing\n", encoding="utf-8")
    config = Config.model_validate(
        {"scan": {"media_paths": [str(tmp_path)]}, "language": {"min_confidence": 1.0}}
    )

    result = run_pipeline(scan(config), config, dry_run=True)

    assert result.skipped_files == []
    assert [r.source.name for r in result.changed_files] == ["Movie (2020).en.srt"]


def test_delete_original_after_conversion_removes_source(tmp_path: Path) -> None:
    _build_library(tmp_path)
    config = Config.model_validate(
        {
            "scan": {"media_paths": [str(tmp_path)]},
            "format": {"convert_to_srt": True, "delete_original_after_conversion": True},
        }
    )
    run_pipeline(scan(config), config, dry_run=False)

    assert not (tmp_path / "Movie (2020).fr.ass").exists()
    assert (tmp_path / "Movie (2020).fr.srt").exists()


def test_detection_corrects_wrong_language_code(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    # Named English but the content is Dutch; high-confidence detection renames it.
    (tmp_path / "Movie (2020).en.srt").write_text(DUTCH_SRT, encoding="utf-8")

    _run(tmp_path, dry_run=False)

    assert not (tmp_path / "Movie (2020).en.srt").exists()
    assert (tmp_path / "Movie (2020).nl.srt").exists()


def test_language_filter_deletes_unwanted_subtitle(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    (tmp_path / "Movie (2020).nl.srt").write_text(DUTCH_SRT, encoding="utf-8")
    config = Config.model_validate(
        {
            "scan": {"media_paths": [str(tmp_path)]},
            "language": {
                "filter": {"enabled": True, "wanted_languages": ["en"], "action": "delete"}
            },
        }
    )

    result = run_pipeline(scan(config), config, dry_run=False)

    assert not (tmp_path / "Movie (2020).nl.srt").exists()
    assert [a.type for a in result.changed_files[0].actions] == [ActionType.DELETE_FILTERED]


def test_language_filter_delete_is_dry_run_safe(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    (tmp_path / "Movie (2020).nl.srt").write_text(DUTCH_SRT, encoding="utf-8")
    config = Config.model_validate(
        {
            "scan": {"media_paths": [str(tmp_path)]},
            "language": {
                "filter": {"enabled": True, "wanted_languages": ["en"], "action": "delete"}
            },
        }
    )

    run_pipeline(scan(config), config, dry_run=True)

    # Dry-run plans the deletion but leaves the file on disk.
    assert (tmp_path / "Movie (2020).nl.srt").exists()


def test_unreadable_file_is_reported_without_stopping_run(tmp_path: Path) -> None:
    _build_library(tmp_path)
    # A dangling symlink is discovered as a subtitle but cannot be read.
    (tmp_path / "Movie (2020).de.srt").symlink_to(tmp_path / "does-not-exist.srt")

    result = _run(tmp_path, dry_run=False)

    assert any(r.error is not None for r in result.file_results)
    # The other files were still processed.
    assert (tmp_path / "Movie (2020).fr.srt").exists()


def test_should_cancel_stops_at_file_boundary_with_partial_results(tmp_path: Path) -> None:
    _build_library(tmp_path)
    config = Config.model_validate({"scan": {"media_paths": [str(tmp_path)]}})
    scan_result = scan(config)

    seen: list[str] = []

    def on_file(result):
        seen.append(result.source.name)

    # Cancel once the first file has been processed: the next boundary stops the run.
    def should_cancel() -> bool:
        return len(seen) >= 1

    with pytest.raises(PipelineCancelled) as exc_info:
        run_pipeline(
            scan_result,
            config,
            dry_run=True,
            on_file=on_file,
            should_cancel=should_cancel,
        )

    # Exactly one file was processed before the stop; its result is carried on the
    # exception so the caller can record the partial progress.
    assert len(seen) == 1
    assert len(exc_info.value.results) == 1
    assert exc_info.value.results[0].source.name == seen[0]


def test_video_audio_is_probed_once_per_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One video matched by two subtitles must trigger a single audio-stream probe,
    # not one per subtitle: the runner shares a MediaProbe across the group.
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    (tmp_path / "Movie (2020).en.srt").write_text(CLEAN_SRT, encoding="utf-8")
    (tmp_path / "Movie (2020).nl.srt").write_text(CLEAN_SRT, encoding="utf-8")

    probes: list[Path] = []

    def counting_probe(video: Path) -> bool:
        probes.append(video)
        return True

    def in_sync(_video, _in, out, **_kwargs):  # type: ignore[no-untyped-def]
        out.write_text(CLEAN_SRT, encoding="utf-8")
        return sync.SyncResult(offset_seconds=0.0, score=1000.0, output=out)

    monkeypatch.setattr(ffmpeg, "has_audio_stream", counting_probe)
    monkeypatch.setattr(sync, "synchronize", in_sync)
    config = Config.model_validate(
        {"scan": {"media_paths": [str(tmp_path)]}, "sync": {"enabled": True}}
    )

    run_pipeline(scan(config), config, dry_run=False)

    assert probes == [tmp_path / "Movie (2020).mkv"]


def test_standalone_match_warning_surfaces_in_pipeline_result(tmp_path: Path) -> None:
    # Two videos share a year and a subtitle matches neither by name, so the matcher
    # leaves it standalone with an ambiguous-year warning. The subtitle itself is
    # clean, so the pipeline records no warning of its own: the scanner warning must
    # still reach the result, or an ambiguous subtitle would vanish from reports.
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Alpha (2020).mkv").write_text("video", encoding="utf-8")
    (tmp_path / "Beta (2020).mkv").write_text("video", encoding="utf-8")
    (tmp_path / "Gamma (2020).en.srt").write_text(CLEAN_SRT, encoding="utf-8")
    config = Config.model_validate({"scan": {"media_paths": [str(tmp_path)]}})

    scan_result = scan(config)
    assert [w.reason.value for w in scan_result.warnings] == ["ambiguous_match"]

    result = run_pipeline(scan_result, config, dry_run=True)

    assert any("matches more than one video" in w for w in result.warnings)
    standalone_result = next(
        r for r in result.file_results if r.source.name == "Gamma (2020).en.srt"
    )
    assert any("matches more than one video" in w for w in standalone_result.warnings)


def test_should_cancel_already_set_stops_before_any_file(tmp_path: Path) -> None:
    _build_library(tmp_path)
    config = Config.model_validate({"scan": {"media_paths": [str(tmp_path)]}})

    with pytest.raises(PipelineCancelled) as exc_info:
        run_pipeline(scan(config), config, dry_run=True, should_cancel=lambda: True)

    assert exc_info.value.results == []
