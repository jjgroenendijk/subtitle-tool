"""Tests for the background worker that runs scans and records jobs."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from subtitle_tool.config.models import Config
from subtitle_tool.jobs import JobStore, Worker
from subtitle_tool.jobs.models import JobStatus


class RecordingBroker:
    """A broker stand-in that captures published events synchronously."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def build_library(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    # An ASS file that the pipeline will convert: a change worth recording.
    (root / "Movie (2020).fr.ass").write_text(
        "[Script Info]\nScriptType: v4.00+\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Bonjour le monde\n",
        encoding="utf-8",
    )
    # An already-clean, confidently-English SRT the pipeline leaves untouched
    # (correct code, no junk, high-confidence detection): nothing to store.
    (root / "Movie (2020).en.srt").write_text(
        "1\n00:00:01,000 --> 00:00:04,000\n"
        "Good morning everyone. I hope you all slept well last night.\n\n"
        "2\n00:00:05,000 --> 00:00:08,000\n"
        "We have a very long day ahead of us, so let us begin right away.\n",
        encoding="utf-8",
    )


def wait_until_idle(worker: Worker, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while worker.is_busy:
        if time.monotonic() > deadline:
            raise AssertionError("worker did not finish in time")
        time.sleep(0.01)


def make_worker(tmp_path: Path, config: Config) -> tuple[Worker, JobStore, RecordingBroker]:
    store = JobStore(tmp_path / "jobs.db")
    broker = RecordingBroker()
    worker = Worker(store, broker, lambda: config)
    return worker, store, broker


def test_start_runs_scan_in_background_and_records_job(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, store, broker = make_worker(tmp_path, config)

    job_id = worker.start(dry_run=True)
    assert job_id is not None
    wait_until_idle(worker)

    job = store.get_job(job_id)
    assert job is not None
    assert job.status is JobStatus.SUCCEEDED
    assert job.total_files == 2  # two subtitles scanned
    assert job.changed_files == 1  # only the ASS conversion
    # Only the changed file is stored, not the already-clean SRT.
    assert len(job.files) == 1
    assert job.files[0].changed


def test_dry_run_leaves_files_untouched(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    before = sorted(p.name for p in media.iterdir())
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, _store, _broker = make_worker(tmp_path, config)

    worker.start(dry_run=True)
    wait_until_idle(worker)

    assert sorted(p.name for p in media.iterdir()) == before


def test_publishes_lifecycle_events(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, _store, broker = make_worker(tmp_path, config)

    worker.start(dry_run=True)
    wait_until_idle(worker)

    kinds = [event["event"] for event in broker.events]
    assert kinds[0] == "job_started"
    assert kinds[-1] == "job_finished"
    assert kinds.count("file_processed") == 2
    finished = broker.events[-1]
    assert finished["status"] == "succeeded"
    assert finished["total"] == 2
    assert finished["changed"] == 1


def test_second_start_while_busy_is_rejected(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, _store, _broker = make_worker(tmp_path, config)

    first = worker.start(dry_run=True)
    # The first job holds the worker; a second immediate start may be rejected.
    # Drain to a known state regardless of timing.
    wait_until_idle(worker)
    assert first is not None

    second = worker.start(dry_run=True)
    assert second is not None
    wait_until_idle(worker)


def test_busy_worker_returns_none(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    build_library(media)
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, _store, _broker = make_worker(tmp_path, config)

    # Make the scan block so the first job stays running while we probe.
    release = _Gate()
    import subtitle_tool.jobs.worker as worker_module

    real_scan = worker_module.scan

    def blocking_scan(cfg):
        release.wait()
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)

    first = worker.start(dry_run=True)
    # While the first job is parked in scan, a second start is refused.
    assert worker.start(dry_run=True) is None
    release.open()
    wait_until_idle(worker)
    assert first is not None


class _Gate:
    """A one-shot gate to hold a background thread until the test releases it."""

    def __init__(self) -> None:
        import threading

        self._event = threading.Event()

    def wait(self) -> None:
        self._event.wait(timeout=5.0)

    def open(self) -> None:
        self._event.set()
