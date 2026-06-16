"""Worker scope tests, focused on non-recursive watcher-triggered scans."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.jobs import ScanRequest
from tests.jobs.test_worker import build_library, make_worker, wait_until_idle


def test_scoped_request_scans_directory_non_recursively(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    build_library(media / "A")
    # A subtitle in a subdirectory of the scoped directory: a non-recursive watcher
    # scan must not descend into it, so it is never processed by the scoped run.
    nested = media / "A" / "Extras"
    nested.mkdir()
    (nested / "Bonus (2020).mkv").write_text("video", encoding="utf-8")
    (nested / "Bonus (2020).fr.ass").write_text(
        "[Script Info]\nScriptType: v4.00+\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Bonjour le monde\n",
        encoding="utf-8",
    )
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, _store, _broker = make_worker(tmp_path, config)

    import subtitle_tool.jobs.worker as worker_module

    recorded: list[bool] = []
    real_scan_paths = worker_module.scan_paths

    def spy_scan_paths(paths, excludes, *, recursive=True):
        recorded.append(recursive)
        return real_scan_paths(paths, excludes, recursive=recursive)

    monkeypatch.setattr(worker_module, "scan_paths", spy_scan_paths)

    job_id = worker.submit(ScanRequest(scope=frozenset({media / "A"}), trigger="watch"))
    assert job_id is not None
    wait_until_idle(worker)

    # The scoped scan ran non-recursively, so the nested subtitle was never touched.
    assert recorded == [False]
    assert (nested / "Bonus (2020).fr.ass").exists()
    assert not (nested / "Bonus (2020).fr.srt").exists()
