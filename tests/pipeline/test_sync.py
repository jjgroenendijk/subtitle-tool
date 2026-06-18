"""Tests for sync correction: the ffsubsync wrapper and the decision step.

The wrapper is exercised end to end against the real ffsubsync, using a subtitle as
the reference so the alignment is deterministic and needs no ffmpeg. The step's
threshold logic (apply within thresholds, skip over the cap, revert on low score,
timeout, no audio) is driven with a stubbed wrapper so each branch is checked exactly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline import ffmpeg, sync
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.steps.sync import correct_sync
from subtitle_tool.pipeline.workitem import WorkItem

if TYPE_CHECKING:
    from pathlib import Path

_REF = (
    "1\n00:00:01,000 --> 00:00:03,000\nHello there friend.\n\n"
    "2\n00:00:05,000 --> 00:00:07,000\nHow are you today.\n\n"
    "3\n00:00:10,000 --> 00:00:12,000\nThe weather is very nice outside.\n"
)
# The same lines shifted five seconds late: ffsubsync should measure offset -5s.
_SHIFTED = (
    "1\n00:00:06,000 --> 00:00:08,000\nHello there friend.\n\n"
    "2\n00:00:10,000 --> 00:00:12,000\nHow are you today.\n\n"
    "3\n00:00:15,000 --> 00:00:17,000\nThe weather is very nice outside.\n"
)


# --- wrapper, against the real ffsubsync (subtitle reference, no ffmpeg needed) ---


def test_synchronize_measures_a_known_shift(tmp_path: Path) -> None:
    ref = tmp_path / "ref.srt"
    ref.write_text(_REF, encoding="utf-8")
    shifted = tmp_path / "in.srt"
    shifted.write_text(_SHIFTED, encoding="utf-8")
    out = tmp_path / "out.srt"

    result = sync.synchronize(ref, shifted, out, max_offset_seconds=30, timeout_seconds=120)

    assert result.offset_seconds == pytest.approx(-5.0, abs=0.2)
    assert result.score > 0
    assert out.exists()


def test_synchronize_raises_on_missing_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = tmp_path / "ref.srt"
    ref.write_text(_REF, encoding="utf-8")
    monkeypatch.setattr(sync, "_executable", lambda: "definitely-not-ffsubsync-xyz")

    with pytest.raises(sync.SyncError, match="not found"):
        sync.synchronize(ref, ref, tmp_path / "o.srt", max_offset_seconds=30, timeout_seconds=10)


def test_synchronize_times_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def slow(*_args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="ffsubsync", timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(sync.SyncTimeout):
        sync.synchronize(
            tmp_path / "r.srt",
            tmp_path / "i.srt",
            tmp_path / "o.srt",
            max_offset_seconds=30,
            timeout_seconds=1,
        )


def test_synchronize_raises_when_no_alignment_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    class _Proc:
        returncode = 0
        stderr = "INFO some unrelated log line\n"
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(sync.SyncError, match="did not produce an alignment"):
        sync.synchronize(
            tmp_path / "r.srt",
            tmp_path / "i.srt",
            tmp_path / "o.srt",
            max_offset_seconds=30,
            timeout_seconds=10,
        )


# --- step decision logic, with a stubbed wrapper ---


def _config(**sync_overrides: object) -> Config:
    return Config.model_validate({"sync": {"enabled": True, **sync_overrides}})


def _item(tmp_path: Path) -> WorkItem:
    sub = tmp_path / "Movie (2020).en.srt"
    sub.write_text(_SHIFTED, encoding="utf-8")
    return WorkItem(
        source=sub,
        target=sub,
        text=_SHIFTED,
        video_stem="Movie (2020)",
        video=tmp_path / "Movie (2020).mkv",
    )


def _forbid_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make a call into ffmpeg fail the test: these paths must short-circuit first."""

    def fail(_video: object) -> bool:
        raise AssertionError("ffmpeg must not be touched on this path")

    monkeypatch.setattr(ffmpeg, "has_audio_stream", fail)


def _stub_sync(monkeypatch: pytest.MonkeyPatch, *, offset: float, score: float) -> None:
    monkeypatch.setattr(ffmpeg, "has_audio_stream", lambda _v: True)

    def fake(video, subtitle_in, subtitle_out, **_kwargs):  # type: ignore[no-untyped-def]
        subtitle_out.write_text("SYNCED CONTENT", encoding="utf-8")
        return sync.SyncResult(offset_seconds=offset, score=score, output=subtitle_out)

    monkeypatch.setattr(sync, "synchronize", fake)


def test_correction_applied_within_thresholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_sync(monkeypatch, offset=-5.0, score=1000.0)
    item = _item(tmp_path)

    correct_sync(item, _config(min_offset_seconds=0.5, max_offset_seconds=60), dry_run=False)

    assert item.text == "SYNCED CONTENT"
    assert [a.type for a in item.actions] == [ActionType.SYNC_CORRECT]
    assert item.warnings == []


def test_correction_skipped_beyond_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_sync(monkeypatch, offset=-90.0, score=1000.0)
    item = _item(tmp_path)

    correct_sync(item, _config(max_offset_seconds=60), dry_run=False)

    assert item.text == _SHIFTED  # original timings kept
    assert item.actions == []
    assert any("exceeds cap" in w for w in item.warnings)


def test_correction_reverted_on_low_score(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_sync(monkeypatch, offset=-5.0, score=2.0)
    item = _item(tmp_path)

    correct_sync(item, _config(min_score=100.0), dry_run=False)

    assert item.text == _SHIFTED
    assert item.actions == []
    assert any("below threshold" in w for w in item.warnings)


def test_small_shift_is_treated_as_in_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_sync(monkeypatch, offset=0.1, score=1000.0)
    item = _item(tmp_path)

    correct_sync(item, _config(min_offset_seconds=0.5), dry_run=False)

    assert item.actions == []
    assert item.warnings == []


def test_dry_run_plans_without_changing_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_sync(monkeypatch, offset=-5.0, score=1000.0)
    item = _item(tmp_path)

    correct_sync(item, _config(), dry_run=True)

    assert item.text == _SHIFTED  # unchanged in dry-run
    assert [a.type for a in item.actions] == [ActionType.SYNC_CORRECT]


def test_skips_when_video_has_no_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg, "has_audio_stream", lambda _v: False)
    item = _item(tmp_path)

    correct_sync(item, _config(), dry_run=False)

    assert item.actions == []
    assert any("no audio track" in w for w in item.warnings)


def test_timeout_skips_with_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg, "has_audio_stream", lambda _v: True)

    def boom(*_a: object, **_k: object) -> None:
        raise sync.SyncTimeout("ffsubsync timed out after 5s")

    monkeypatch.setattr(sync, "synchronize", boom)
    item = _item(tmp_path)

    correct_sync(item, _config(), dry_run=False)

    assert item.actions == []
    assert any("timed out" in w for w in item.warnings)


def test_disabled_is_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_a: object, **_k: object) -> None:
        raise AssertionError("ffsubsync must not run when sync is disabled")

    monkeypatch.setattr(ffmpeg, "has_audio_stream", fail)
    item = _item(tmp_path)

    correct_sync(item, Config(), dry_run=False)

    assert item.actions == []
    assert item.warnings == []


def test_standalone_subtitle_is_not_synced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_probe(monkeypatch)
    sub = tmp_path / "loose.en.srt"
    sub.write_text(_SHIFTED, encoding="utf-8")
    item = WorkItem(source=sub, target=sub, text=_SHIFTED, video=None)

    correct_sync(item, _config(), dry_run=False)

    assert item.actions == []
    assert item.warnings == []


def test_non_srt_target_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_probe(monkeypatch)
    sub = tmp_path / "Movie (2020).en.ass"
    sub.write_text("[Script Info]\n", encoding="utf-8")
    item = WorkItem(
        source=sub, target=sub, text="[Script Info]\n", video=tmp_path / "Movie (2020).mkv"
    )

    correct_sync(item, _config(), dry_run=False)

    assert item.actions == []
    assert item.warnings == []
