"""Worker scope tests, focused on non-recursive watcher-triggered scans."""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_tool.jobs import ScanRequest
from tests.helpers import (
    ASS_SUBTITLE,
    build_library,
    make_worker,
    media_config,
    wait_for_worker,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_scoped_request_scans_directory_non_recursively(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    build_library(media / "A", clean_srt=True)
    # A subtitle in a subdirectory of the scoped directory: a non-recursive watcher
    # scan must not descend into it, so it is never processed by the scoped run.
    nested = media / "A" / "Extras"
    nested.mkdir()
    (nested / "Bonus (2020).mkv").write_text("video", encoding="utf-8")
    (nested / "Bonus (2020).fr.ass").write_text(ASS_SUBTITLE, encoding="utf-8")
    worker, _store, _broker = make_worker(tmp_path, media_config(media))

    import subtitle_tool.jobs.worker as worker_module

    recorded: list[bool] = []
    real_scan_paths = worker_module.scan_paths

    def spy_scan_paths(paths, excludes, *, recursive=True):
        recorded.append(recursive)
        return real_scan_paths(paths, excludes, recursive=recursive)

    monkeypatch.setattr(worker_module, "scan_paths", spy_scan_paths)

    job_id = worker.submit(ScanRequest(scope=frozenset({media / "A"}), trigger="watch"))
    assert job_id is not None
    wait_for_worker(worker)

    # The scoped scan ran non-recursively, so the nested subtitle was never touched.
    assert recorded == [False]
    assert (nested / "Bonus (2020).fr.ass").exists()
    assert not (nested / "Bonus (2020).fr.srt").exists()
