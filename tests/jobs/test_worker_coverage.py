"""Worker tests for the scan-coverage counters surfaced in the UI.

These cover the inventory counts (videos and subtitles found), the
processed-vs-total split, and the unwanted-subtitle tally, all recorded on the job
row and published on the ``job_finished`` event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import build_library, make_worker, media_config, wait_for_worker

if TYPE_CHECKING:
    from pathlib import Path


def test_records_inventory_coverage_counters(tmp_path: Path) -> None:
    # One video and two subtitles in the inventory; the dry run processes both.
    media = tmp_path / "media"
    build_library(media, clean_srt=True)
    worker, store, broker = make_worker(tmp_path, media_config(media))

    job_id = worker.start(dry_run=True)
    assert job_id is not None
    # Wait on the worker thread so the job_finished event is published before the
    # broker is read; the store row is committed earlier, so get_job is safe too.
    wait_for_worker(worker)
    job = store.get_job(job_id)
    assert job is not None

    assert job.videos_found == 1
    assert job.subtitles_found == 2
    assert job.processed_files == 2
    assert job.total_files == 2
    assert job.unwanted_subtitles == 0
    # The same coverage rides the job_finished event for the live dashboard.
    finished = broker.events[-1]
    assert finished["event"] == "job_finished"
    assert finished["videos_found"] == 1
    assert finished["subtitles_found"] == 2
    assert finished["processed"] == 2
    assert finished["unwanted"] == 0


def test_counts_unwanted_subtitles_removed_by_filter(tmp_path: Path, monkeypatch) -> None:
    # The language filter deleting a subtitle is recorded as an unwanted removal,
    # counted from the DELETE_FILTERED action the detection step records.
    media = tmp_path / "media"
    build_library(media, clean_srt=True)
    worker, store, broker = make_worker(tmp_path, media_config(media))

    import subtitle_tool.jobs.worker as worker_module
    from subtitle_tool.pipeline import FileResult
    from subtitle_tool.pipeline.models import Action, ActionType

    def fake_run_pipeline(scan_result, cfg, *, dry_run, on_file=None, **_kwargs):
        emitted = [
            FileResult(
                source=media / "Movie (2020).fr.srt",
                target=media / "Movie (2020).fr.srt",
                actions=[Action(ActionType.DELETE_FILTERED, "delete unwanted-language (fr)")],
            ),
            FileResult(source=media / "Movie (2020).en.srt", target=media / "Movie (2020).en.srt"),
        ]
        for result in emitted:
            if on_file is not None:
                on_file(result)

    monkeypatch.setattr(worker_module, "run_pipeline", fake_run_pipeline)

    job_id = worker.start(dry_run=True)
    assert job_id is not None
    wait_for_worker(worker)
    job = store.get_job(job_id)
    assert job is not None

    assert job.unwanted_subtitles == 1
    assert job.changed_files == 1  # the delete is the only planned change
    finished = broker.events[-1]
    assert finished["unwanted"] == 1
