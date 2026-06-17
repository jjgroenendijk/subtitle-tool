"""Shared, test-local setup helpers for the worker, web, index, and pipeline tests.

These utilities exist only to keep repeated test setup out of the individual test
modules. They are deliberately not part of the package's public API; nothing under
``src/`` imports from here.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from subtitle_tool.config.models import Config
from subtitle_tool.index import IndexStore
from subtitle_tool.jobs import JobStore, Worker

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

# A French ASS subtitle the pipeline converts to SRT: a change worth recording.
ASS_SUBTITLE = (
    "[Script Info]\nScriptType: v4.00+\n[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Bonjour le monde\n"
)
# A long, already-clean, confidently-English SRT (correct code, no junk, high-confidence
# detection) the pipeline leaves untouched: nothing to store.
CLEAN_EN_SUBTITLE = (
    "1\n00:00:01,000 --> 00:00:04,000\n"
    "Good morning everyone. I hope you all slept well last night.\n\n"
    "2\n00:00:05,000 --> 00:00:08,000\n"
    "We have a very long day ahead of us, so let us begin right away.\n"
)


def media_config(media: Path, **sections: Any) -> Config:
    """Build a Config rooted at ``media``, merging any extra top-level sections.

    ``media_config(path, format={"convert_to_srt": True})`` adds the ``format`` section
    alongside the scanned media path.
    """
    data: dict[str, Any] = {"scan": {"media_paths": [str(media)]}}
    data.update(sections)
    return Config.model_validate(data)


def build_library(root: Path, *, convertible: bool = True, clean_srt: bool = False) -> None:
    """Create a media library under ``root``.

    convertible: add a French ``.ass`` the pipeline converts (a recorded change).
    clean_srt: add a confidently-English ``.srt`` the pipeline leaves untouched.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    if convertible:
        (root / "Movie (2020).fr.ass").write_text(ASS_SUBTITLE, encoding="utf-8")
    if clean_srt:
        (root / "Movie (2020).en.srt").write_text(CLEAN_EN_SUBTITLE, encoding="utf-8")


class RecordingBroker:
    """A broker stand-in that captures published events synchronously."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def make_worker(tmp_path: Path, config: Config) -> tuple[Worker, JobStore, RecordingBroker]:
    store = JobStore(tmp_path / "jobs.db")
    broker = RecordingBroker()
    worker = Worker(store, broker, lambda: config)
    return worker, store, broker


def make_indexed_worker(tmp_path: Path, config: Config) -> tuple[Worker, JobStore, IndexStore]:
    """Like :func:`make_worker`, but wired to a media index for reconcile tests."""
    store = JobStore(tmp_path / "jobs.db")
    index = IndexStore(tmp_path / "index.db")
    worker = Worker(store, RecordingBroker(), lambda: config, index)
    return worker, store, index


def wait_for_worker(worker: Worker, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while worker.is_busy:
        if time.monotonic() > deadline:
            raise AssertionError("worker did not finish in time")
        time.sleep(0.01)


def wait_idle(client: TestClient, timeout: float = 5.0) -> None:
    wait_for_worker(client.app.state.worker, timeout)


class Gate:
    """A one-shot gate to hold a background thread until the test releases it."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def wait(self, timeout: float = 5.0) -> None:
        self._event.wait(timeout=timeout)

    def open(self) -> None:
        self._event.set()


def block_worker_scan(monkeypatch: Any) -> tuple[Gate, Gate]:
    """Park the worker inside ``scan()`` until the test releases it.

    Returns ``(entered, release)``: ``entered`` opens once a job reaches ``scan()``,
    and the job blocks there until the test calls ``release.open()``. Because the gate
    stays open, any later job in the same test runs through ``scan()`` normally.
    """
    import subtitle_tool.jobs.worker as worker_module

    entered, release = Gate(), Gate()
    real_scan = worker_module.scan

    def blocking_scan(cfg):  # type: ignore[no-untyped-def]
        entered.open()
        release.wait()
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)
    return entered, release
