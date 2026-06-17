"""Worker tests for scanner match warnings reaching job history."""

from __future__ import annotations

from pathlib import Path

from tests.helpers import CLEAN_EN_SUBTITLE, make_worker, media_config, wait_for_worker


def test_standalone_match_warning_is_recorded_in_job_history(tmp_path: Path) -> None:
    # An ambiguous standalone subtitle is otherwise clean, so the pipeline records no
    # warning for it. The scanner's match warning must still land in job history and
    # the job's warning count, or an unmatched subtitle disappears from the UI.
    media = tmp_path / "media"
    media.mkdir(parents=True, exist_ok=True)
    # Two videos share a year; the subtitle matches neither by name, so the matcher
    # leaves it standalone with an ambiguous-year warning.
    (media / "Alpha (2020).mkv").write_text("video", encoding="utf-8")
    (media / "Beta (2020).mkv").write_text("video", encoding="utf-8")
    # Long, confidently-English content so detection adds no warning of its own and
    # the only warning is the scanner's ambiguous match.
    (media / "Gamma (2020).en.srt").write_text(CLEAN_EN_SUBTITLE, encoding="utf-8")
    worker, store, _broker = make_worker(tmp_path, media_config(media))

    job_id = worker.start(dry_run=True)
    assert job_id is not None
    wait_for_worker(worker)

    job = store.get_job(job_id)
    assert job is not None
    assert job.warning_count == 1
    standalone = next(f for f in job.files if f.source.endswith("Gamma (2020).en.srt"))
    assert any("matches more than one video" in w for w in standalone.warnings)
