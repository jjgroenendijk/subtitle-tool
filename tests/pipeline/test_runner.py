"""End-to-end pipeline tests over a fixture library in dry-run and real mode."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline import run_pipeline
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


def test_real_run_is_idempotent(tmp_path: Path) -> None:
    _build_library(tmp_path)
    _run(tmp_path, dry_run=False)
    after_first = _snapshot(tmp_path)

    second = _run(tmp_path, dry_run=False)

    assert second.changed_files == []
    assert _snapshot(tmp_path) == after_first


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
