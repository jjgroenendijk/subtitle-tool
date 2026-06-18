"""Tests for the SQLite job history store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_tool.jobs import JobStore
from subtitle_tool.jobs.models import JobFile, JobStatus

if TYPE_CHECKING:
    from pathlib import Path


def make_store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def test_create_job_starts_running(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    job_id = store.create_job("real")
    job = store.get_job(job_id)

    assert job is not None
    assert job.status is JobStatus.RUNNING
    assert job.mode == "real"
    assert job.finished_at is None
    assert job.files == []


def test_records_files_and_summary_on_finish(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    job_id = store.create_job("real")

    store.add_file(
        job_id,
        JobFile(
            source="/m/a.srt",
            target="/m/a.en.srt",
            actions=[("rename", "renamed to a.en.srt")],
            warnings=[],
        ),
    )
    store.add_file(
        job_id,
        JobFile(source="/m/b.srt", target="/m/b.srt", warnings=["low confidence"]),
    )
    store.finish_job(
        job_id,
        JobStatus.SUCCEEDED,
        total_files=5,
        changed_files=1,
        warning_count=1,
        error_files=0,
    )

    job = store.get_job(job_id)
    assert job is not None
    assert job.status is JobStatus.SUCCEEDED
    assert job.finished_at is not None
    assert job.total_files == 5
    assert job.changed_files == 1
    assert job.warning_count == 1
    assert len(job.files) == 2
    # Action tuples survive the JSON round-trip.
    assert job.files[0].actions == [("rename", "renamed to a.en.srt")]
    assert job.files[1].warnings == ["low confidence"]


def test_list_jobs_returns_newest_first_without_files(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.create_job("dry-run")
    second = store.create_job("real")
    store.add_file(first, JobFile(source="/m/a.srt", target="/m/a.srt", warnings=["w"]))

    jobs = store.list_jobs()

    assert [job.id for job in jobs] == [second, first]
    # Summaries carry no per-file rows.
    assert all(job.files == [] for job in jobs)


def test_prune_keeps_only_the_most_recent(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    ids = [store.create_job("real") for _ in range(5)]

    removed = store.prune(2)

    assert removed == 3
    remaining = {job.id for job in store.list_jobs()}
    assert remaining == set(ids[-2:])


def test_prune_cascades_to_file_rows(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    old = store.create_job("real")
    store.add_file(old, JobFile(source="/m/a.srt", target="/m/a.srt", warnings=["w"]))
    store.create_job("real")

    store.prune(1)

    assert store.get_job(old) is None


def test_clear_removes_finished_jobs_but_keeps_running(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    finished = store.create_job("real")
    store.add_file(finished, JobFile(source="/m/a.srt", target="/m/a.srt", warnings=["w"]))
    store.finish_job(
        finished,
        JobStatus.SUCCEEDED,
        total_files=1,
        changed_files=0,
        warning_count=1,
        error_files=0,
    )
    running = store.create_job("real")

    removed = store.clear()

    assert removed == 1
    # The finished job and its per-file rows are gone; the running job stays.
    assert store.get_job(finished) is None
    assert {job.id for job in store.list_jobs()} == {running}


def test_get_unknown_job_returns_none(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    assert store.get_job(999) is None


def test_mark_running_interrupted_only_touches_running_jobs(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    running = store.create_job("real")
    finished = store.create_job("real")
    store.finish_job(
        finished,
        JobStatus.SUCCEEDED,
        total_files=1,
        changed_files=0,
        warning_count=0,
        error_files=0,
    )

    count = store.mark_running_interrupted()

    assert count == 1
    interrupted = store.get_job(running)
    assert interrupted is not None
    assert interrupted.status is JobStatus.INTERRUPTED
    assert interrupted.finished_at is not None
    # A run that already finished is left alone.
    done = store.get_job(finished)
    assert done is not None
    assert done.status is JobStatus.SUCCEEDED


def test_mark_running_interrupted_is_a_noop_without_running_jobs(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    assert store.mark_running_interrupted() == 0
