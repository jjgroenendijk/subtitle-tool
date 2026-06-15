"""Worker tests for scanner match warnings reaching job history."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from tests.jobs.test_worker import make_worker, wait_until_idle


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
    (media / "Gamma (2020).en.srt").write_text(
        "1\n00:00:01,000 --> 00:00:04,000\n"
        "Good morning everyone. I hope you all slept well last night.\n\n"
        "2\n00:00:05,000 --> 00:00:08,000\n"
        "We have a very long day ahead of us, so let us begin right away.\n",
        encoding="utf-8",
    )
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, store, _broker = make_worker(tmp_path, config)

    job_id = worker.start(dry_run=True)
    assert job_id is not None
    wait_until_idle(worker)

    job = store.get_job(job_id)
    assert job is not None
    assert job.warning_count == 1
    standalone = next(f for f in job.files if f.source.endswith("Gamma (2020).en.srt"))
    assert any("matches more than one video" in w for w in standalone.warnings)
