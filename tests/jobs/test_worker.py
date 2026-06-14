"""Tests for the background worker that runs scans and records jobs."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from subtitle_tool.config.models import Config
from subtitle_tool.index import IndexStore
from subtitle_tool.jobs import JobStore, ScanRequest, Worker, merge_requests
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


def test_scoped_request_scans_only_those_directories(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    build_library(media / "A")
    build_library(media / "B")
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, store, _broker = make_worker(tmp_path, config)

    import subtitle_tool.jobs.worker as worker_module

    recorded: list[list[str]] = []
    real_scan_paths = worker_module.scan_paths

    def spy_scan_paths(paths, excludes):
        recorded.append(list(paths))
        return real_scan_paths(paths, excludes)

    monkeypatch.setattr(worker_module, "scan_paths", spy_scan_paths)

    job_id = worker.submit(ScanRequest(scope=frozenset({media / "A"}), trigger="watch"))
    assert job_id is not None
    wait_until_idle(worker)

    # Only directory A was walked, not the whole media root.
    assert recorded == [[str(media / "A")]]
    job = store.get_job(job_id)
    assert job is not None
    assert job.total_files == 2  # the two subtitles under A only


def test_triggers_during_a_job_collapse_into_one_followup(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    build_library(media / "A")
    build_library(media / "B")
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, store, _broker = make_worker(tmp_path, config)

    import subtitle_tool.jobs.worker as worker_module

    gate = _Gate()
    entered = _Gate()
    real_scan = worker_module.scan

    def blocking_scan(cfg):
        entered.open()
        gate.wait()
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)

    scoped_paths: list[list[str]] = []
    real_scan_paths = worker_module.scan_paths

    def spy_scan_paths(paths, excludes):
        scoped_paths.append(list(paths))
        return real_scan_paths(paths, excludes)

    monkeypatch.setattr(worker_module, "scan_paths", spy_scan_paths)

    first = worker.submit(ScanRequest(trigger="manual"))  # full scan, blocks in scan()
    entered.wait()
    # Three triggers arrive while the first job runs; they collapse into one follow-up
    # whose scope is the union of the watcher scopes.
    assert worker.submit(ScanRequest(scope=frozenset({media / "A"}), trigger="watch")) is None
    assert worker.submit(ScanRequest(scope=frozenset({media / "B"}), trigger="watch")) is None
    assert worker.submit(ScanRequest(scope=frozenset({media / "A"}), trigger="watch")) is None
    gate.open()
    wait_until_idle(worker)

    jobs = store.list_jobs()
    assert len(jobs) == 2  # the blocked full scan plus exactly one collapsed follow-up
    assert first is not None
    # The single follow-up walked both changed directories, merged.
    assert len(scoped_paths) == 1
    assert set(scoped_paths[0]) == {str(media / "A"), str(media / "B")}


def test_full_scan_trigger_subsumes_pending_scope(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    build_library(media / "A")
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, _store, _broker = make_worker(tmp_path, config)

    import subtitle_tool.jobs.worker as worker_module

    gate = _Gate()
    entered = _Gate()
    real_scan = worker_module.scan

    def blocking_scan(cfg):
        entered.open()
        gate.wait()
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)

    scoped_paths: list[list[str]] = []
    monkeypatch.setattr(
        worker_module,
        "scan_paths",
        lambda paths, excludes: scoped_paths.append(list(paths)),
    )

    worker.submit(ScanRequest(trigger="manual"))
    entered.wait()
    worker.submit(ScanRequest(scope=frozenset({media / "A"}), trigger="watch"))
    # A later full-scan trigger replaces the scoped pending request entirely.
    worker.submit(ScanRequest(trigger="schedule"))
    gate.open()
    wait_until_idle(worker)

    # The follow-up was a full scan, so scan_paths (scoped) was never used.
    assert scoped_paths == []


def build_clean_library(root: Path) -> None:
    """A library the pipeline leaves untouched, so no new files appear between runs."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    (root / "Movie (2020).en.srt").write_text(
        "1\n00:00:01,000 --> 00:00:04,000\n"
        "Good morning everyone. I hope you all slept well last night.\n\n"
        "2\n00:00:05,000 --> 00:00:08,000\n"
        "We have a very long day ahead of us, so let us begin right away.\n",
        encoding="utf-8",
    )


def test_index_skips_unchanged_files_on_a_second_run(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_clean_library(media)
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    store = JobStore(tmp_path / "jobs.db")
    index = IndexStore(tmp_path / "index.db")
    worker = Worker(store, RecordingBroker(), lambda: config, index)

    first = worker.start(dry_run=False)
    assert first is not None
    wait_until_idle(worker)
    first_job = store.get_job(first)
    assert first_job is not None
    assert first_job.total_files == 1  # the one (already clean) subtitle is new

    second = worker.start(dry_run=False)
    assert second is not None
    wait_until_idle(worker)
    second_job = store.get_job(second)
    assert second_job is not None
    # The library is clean and unchanged, so the indexed files are all skipped.
    assert second_job.total_files == 0
    assert second_job.changed_files == 0
    assert second_job.status is JobStatus.SUCCEEDED


def test_index_records_videos_for_the_library_view(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    store = JobStore(tmp_path / "jobs.db")
    index = IndexStore(tmp_path / "index.db")
    worker = Worker(store, RecordingBroker(), lambda: config, index)

    worker.start(dry_run=False)
    wait_until_idle(worker)

    library = index.library()
    assert [Path(entry.video.path).name for entry in library] == ["Movie (2020).mkv"]


def test_cancel_stops_running_job_and_records_cancelled(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    build_library(media)
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, store, broker = make_worker(tmp_path, config)

    import subtitle_tool.jobs.worker as worker_module

    gate = _Gate()
    entered = _Gate()
    real_scan = worker_module.scan

    def blocking_scan(cfg):
        entered.open()
        gate.wait()
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)

    job_id = worker.start(dry_run=False)
    assert job_id is not None
    entered.wait()
    # The job is parked in scan; a stop request for it is accepted.
    assert worker.cancel(job_id) is True
    gate.open()
    wait_until_idle(worker)

    job = store.get_job(job_id)
    assert job is not None
    assert job.status is JobStatus.CANCELLED
    assert job.finished_at is not None
    assert broker.events[-1]["status"] == "cancelled"


def test_cancel_drops_queued_followup(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    build_library(media / "A")
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, store, _broker = make_worker(tmp_path, config)

    import subtitle_tool.jobs.worker as worker_module

    gate = _Gate()
    entered = _Gate()
    real_scan = worker_module.scan

    def blocking_scan(cfg):
        entered.open()
        gate.wait()
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)

    first = worker.start(dry_run=False)
    entered.wait()
    # A follow-up queues while the first job runs, then the user stops the job.
    assert worker.submit(ScanRequest(scope=frozenset({media / "A"}), trigger="watch")) is None
    assert worker.cancel(first) is True
    gate.open()
    wait_until_idle(worker)

    # Stopping dropped the queued follow-up: only the one (cancelled) job exists.
    jobs = store.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].status is JobStatus.CANCELLED


def test_cancel_when_idle_is_a_noop(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, _store, _broker = make_worker(tmp_path, config)

    assert worker.cancel() is False
    assert worker.current_job_id is None


def test_start_works_normally_after_a_cancel(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    build_library(media)
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, store, _broker = make_worker(tmp_path, config)

    import subtitle_tool.jobs.worker as worker_module

    gate = _Gate()
    entered = _Gate()
    real_scan = worker_module.scan

    def blocking_scan(cfg):
        entered.open()
        gate.wait()
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)

    first = worker.start(dry_run=True)
    entered.wait()
    worker.cancel(first)
    gate.open()
    wait_until_idle(worker)

    # The cancel flag is cleared per run, so the next job completes normally.
    monkeypatch.setattr(worker_module, "scan", real_scan)
    second = worker.start(dry_run=True)
    assert second is not None
    wait_until_idle(worker)
    second_job = store.get_job(second)
    assert second_job is not None
    assert second_job.status is JobStatus.SUCCEEDED


def test_merge_requests_unions_scopes_and_prefers_real() -> None:
    a = ScanRequest(scope=frozenset({Path("/a")}), trigger="watch")
    b = ScanRequest(scope=frozenset({Path("/b")}), trigger="watch")
    merged = merge_requests(a, b)
    assert merged.scope == frozenset({Path("/a"), Path("/b")})

    # A None scope (full scan) wins over any scoped request, in either order.
    full = ScanRequest(scope=None, trigger="schedule")
    assert merge_requests(a, full).scope is None
    assert merge_requests(full, a).scope is None

    # The first non-None argument's prior value is kept; merging onto None returns it.
    assert merge_requests(None, a) is a

    # A real run dominates a dry run; two dry runs stay dry.
    assert merge_requests(ScanRequest(dry_run=True), ScanRequest(dry_run=False)).dry_run is False
    assert merge_requests(ScanRequest(dry_run=True), ScanRequest(dry_run=True)).dry_run is True


class _Gate:
    """A one-shot gate to hold a background thread until the test releases it."""

    def __init__(self) -> None:
        import threading

        self._event = threading.Event()

    def wait(self) -> None:
        self._event.wait(timeout=5.0)

    def open(self) -> None:
        self._event.set()
