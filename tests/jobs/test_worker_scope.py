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

    def spy_scan_paths(paths, excludes, *, recursive=True, exclude_roots=None):
        recorded.append(recursive)
        return real_scan_paths(paths, excludes, recursive=recursive, exclude_roots=exclude_roots)

    monkeypatch.setattr(worker_module, "scan_paths", spy_scan_paths)

    job_id = worker.submit(ScanRequest(scope=frozenset({media / "A"}), trigger="watch"))
    assert job_id is not None
    wait_for_worker(worker)

    # The scoped scan ran non-recursively, so the nested subtitle was never touched.
    assert recorded == [False]
    assert (nested / "Bonus (2020).fr.ass").exists()
    assert not (nested / "Bonus (2020).fr.srt").exists()


def test_scoped_scan_honours_root_relative_excludes(tmp_path: Path) -> None:
    # A live change inside an excluded directory re-roots the scoped scan at that
    # directory. The exclude pattern is root-relative, so without carrying the media
    # root the scan would no longer see the ``excluded`` segment and would process the
    # file. The worker passes the media paths as exclude roots, so the file is skipped.
    media = tmp_path / "media"
    excluded = media / "excluded"
    build_library(excluded, clean_srt=False)
    config = media_config(
        media,
        scan={"media_paths": [str(media)], "exclude_patterns": ["excluded/"]},
    )
    worker, _store, _broker = make_worker(tmp_path, config)

    job_id = worker.submit(ScanRequest(scope=frozenset({excluded}), trigger="watch"))
    assert job_id is not None
    wait_for_worker(worker)

    # The convertible subtitle in the excluded directory was left untouched: no
    # conversion ran, so no ``.srt`` was produced.
    assert (excluded / "Movie (2020).fr.ass").exists()
    assert not (excluded / "Movie (2020).fr.srt").exists()
