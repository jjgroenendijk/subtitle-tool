"""Dry-run planning of the video phase, isolated from a real ffmpeg.

These tests stub ``ffmpeg.probe_subtitle_streams`` so they exercise the planning
logic without invoking ffmpeg, and so run even where ffmpeg is not installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline import ffmpeg
from subtitle_tool.pipeline.stream_variants import SubtitleVariant
from subtitle_tool.pipeline.video import process_video

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _config(tmp_path: Path, **extraction: object) -> Config:
    return Config.model_validate(
        {"scan": {"media_paths": [str(tmp_path)]}, "extraction": {"enabled": True, **extraction}}
    )


def _stub_streams(monkeypatch: pytest.MonkeyPatch, streams: list[ffmpeg.SubtitleStream]) -> None:
    monkeypatch.setattr(ffmpeg, "probe_subtitle_streams", lambda _video: streams)


def test_dry_run_suffixes_duplicate_planned_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two English text streams both map to Movie.en.srt; a real run would suffix the
    # second, so the dry run must plan distinct targets rather than the same name twice.
    video = tmp_path / "Movie.mkv"
    streams = [
        ffmpeg.SubtitleStream(index=2, codec="subrip", language="eng"),
        ffmpeg.SubtitleStream(index=3, codec="subrip", language="eng"),
    ]
    monkeypatch.setattr(ffmpeg, "probe_subtitle_streams", lambda _video: streams)

    result, extracted = process_video(video, _config(tmp_path), dry_run=True)

    assert extracted == []
    assert result is not None
    descriptions = [a.description for a in result.actions]
    assert descriptions == [
        "extract stream 2 (eng) to Movie.en.srt",
        "extract stream 3 (eng) to Movie.en (1).srt",
    ]


def test_dry_run_suffixes_against_existing_file_and_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An existing Movie.en.srt plus two English streams: the first plan takes the (1)
    # slot already on disk, the second must step past both to (2).
    video = tmp_path / "Movie.mkv"
    (tmp_path / "Movie.en.srt").write_text("keep me", encoding="utf-8")
    streams = [
        ffmpeg.SubtitleStream(index=2, codec="subrip", language="eng"),
        ffmpeg.SubtitleStream(index=3, codec="subrip", language="eng"),
    ]
    monkeypatch.setattr(ffmpeg, "probe_subtitle_streams", lambda _video: streams)

    result, _extracted = process_video(video, _config(tmp_path), dry_run=True)

    assert result is not None
    descriptions = [a.description for a in result.actions]
    assert descriptions == [
        "extract stream 2 (eng) to Movie.en (1).srt",
        "extract stream 3 (eng) to Movie.en (2).srt",
    ]


def test_same_language_variants_get_distinct_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Normal, forced, and SDH English streams must land on distinct Plex-flagged names
    # rather than collapsing into numeric collision suffixes.
    video = tmp_path / "Movie.mkv"
    _stub_streams(
        monkeypatch,
        [
            ffmpeg.SubtitleStream(2, "subrip", "eng", SubtitleVariant.NORMAL),
            ffmpeg.SubtitleStream(3, "subrip", "eng", SubtitleVariant.FORCED),
            ffmpeg.SubtitleStream(4, "subrip", "eng", SubtitleVariant.SDH),
        ],
    )

    result, _extracted = process_video(video, _config(tmp_path), dry_run=True)

    assert result is not None
    assert [a.description for a in result.actions] == [
        "extract stream 2 (eng) to Movie.en.srt",
        "extract stream 3 (eng) to Movie.en.forced.srt",
        "extract stream 4 (eng) to Movie.en.sdh.srt",
    ]


def test_keep_embedded_variant_is_neither_extracted_nor_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With forced set to keep_embedded, only the normal stream is extracted, and the
    # forced stream is left out of the remux drop set.
    video = tmp_path / "Movie.mkv"
    _stub_streams(
        monkeypatch,
        [
            ffmpeg.SubtitleStream(2, "subrip", "eng", SubtitleVariant.NORMAL),
            ffmpeg.SubtitleStream(3, "subrip", "eng", SubtitleVariant.FORCED),
        ],
    )
    config = _config(tmp_path, forced="keep_embedded", remux=True)

    result, _extracted = process_video(video, config, dry_run=True)

    assert result is not None
    descriptions = [a.description for a in result.actions]
    assert "extract stream 2 (eng) to Movie.en.srt" in descriptions
    assert not any("stream 3" in d for d in descriptions)
    # The remux drops exactly the one extracted stream, not the kept-embedded one.
    assert any("drop 1 extracted stream" in d for d in descriptions)


def test_unknown_variant_kept_embedded_by_default_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "Movie.mkv"
    _stub_streams(monkeypatch, [ffmpeg.SubtitleStream(2, "subrip", "eng", SubtitleVariant.UNKNOWN)])

    result, extracted = process_video(video, _config(tmp_path), dry_run=True)

    assert extracted == []
    assert result is not None
    assert not result.actions
    assert any("could not be determined" in w for w in result.warnings)


def test_unknown_variant_extracts_without_a_flag_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Opting the unknown class into extraction names it with the base language only,
    # since guessing a forced/sdh flag would mislabel it.
    video = tmp_path / "Movie.mkv"
    _stub_streams(monkeypatch, [ffmpeg.SubtitleStream(2, "subrip", "eng", SubtitleVariant.UNKNOWN)])

    result, _extracted = process_video(video, _config(tmp_path, unknown="extract"), dry_run=True)

    assert result is not None
    assert [a.description for a in result.actions] == ["extract stream 2 (eng) to Movie.en.srt"]


def test_one_per_language_extracts_only_the_normal_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Normal + SDH English: "one per language" keeps only the preferred normal stream.
    video = tmp_path / "Movie.mkv"
    _stub_streams(
        monkeypatch,
        [
            ffmpeg.SubtitleStream(2, "subrip", "eng", SubtitleVariant.NORMAL),
            ffmpeg.SubtitleStream(3, "subrip", "eng", SubtitleVariant.SDH),
        ],
    )
    config = _config(tmp_path, selection_mode="one_per_language")

    result, _extracted = process_video(video, config, dry_run=True)

    assert result is not None
    assert [a.description for a in result.actions] == [
        "extract stream 2 (eng) to Movie.en.srt",
    ]


def test_one_per_language_falls_back_to_sdh_when_no_normal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No normal stream: the SDH stream is the fallback and lands on its .sdh name.
    video = tmp_path / "Movie.mkv"
    _stub_streams(
        monkeypatch,
        [
            ffmpeg.SubtitleStream(3, "subrip", "eng", SubtitleVariant.SDH),
            ffmpeg.SubtitleStream(4, "subrip", "eng", SubtitleVariant.FORCED),
        ],
    )
    config = _config(tmp_path, selection_mode="one_per_language")

    result, _extracted = process_video(video, config, dry_run=True)

    assert result is not None
    assert [a.description for a in result.actions] == [
        "extract stream 3 (eng) to Movie.en.sdh.srt",
    ]
