"""Tests for the filesystem watcher's stability tracker and scan wiring."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import (
    FileClosedEvent,
    FileClosedNoWriteEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileOpenedEvent,
)

from subtitle_tool.config.models import Config
from subtitle_tool.watcher import (
    StabilityTracker,
    Watcher,
    WatchRoot,
    _EventHandler,
    _make_event_rewriter,
    resolve_watch_roots,
)

if TYPE_CHECKING:
    from subtitle_tool.jobs import ScanRequest


class FakeClock:
    """A monotonic clock the test advances explicitly, for deterministic debounce."""

    def __init__(self) -> None:
        self._now = 0.0

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def make_tracker(window: float, clock: FakeClock) -> StabilityTracker:
    return StabilityTracker(window, clock=clock.now)


def test_stable_file_becomes_ready_after_window(tmp_path: Path) -> None:
    clock = FakeClock()
    tracker = make_tracker(10.0, clock)
    sub = tmp_path / "movie.srt"
    sub.write_text("hello", encoding="utf-8")

    tracker.note(sub)
    # First poll only samples the file; it cannot yet be known to be stable.
    assert tracker.poll() == set()
    clock.advance(10.0)
    assert tracker.poll() == {tmp_path}
    # Once reported, the file is no longer tracked.
    assert tracker.poll() == set()
    assert tracker.tracked_count == 0


def test_slow_copy_is_not_ready_until_writes_stop(tmp_path: Path) -> None:
    clock = FakeClock()
    tracker = make_tracker(20.0, clock)
    sub = tmp_path / "download.srt"
    sub.write_text("chunk", encoding="utf-8")
    tracker.note(sub)
    tracker.poll()  # initial sample at t=0

    # Simulate a copy that keeps growing: every interval the size changes, so the
    # stability window keeps resetting and the directory is never queued mid-copy.
    for step in range(5):
        clock.advance(5.0)
        sub.write_text("chunk" * (step + 2), encoding="utf-8")
        assert tracker.poll() == set()

    # The copy finishes; after the full window with no change, it settles.
    clock.advance(25.0)
    assert tracker.poll() == {tmp_path}


def test_growth_within_window_resets_stability(tmp_path: Path) -> None:
    clock = FakeClock()
    tracker = make_tracker(10.0, clock)
    sub = tmp_path / "a.srt"
    sub.write_text("x", encoding="utf-8")
    tracker.note(sub)
    assert tracker.poll() == set()

    clock.advance(5.0)
    sub.write_text("xx", encoding="utf-8")  # changed before the window elapsed
    assert tracker.poll() == set()

    clock.advance(5.0)  # only 5s of stability so far
    assert tracker.poll() == set()
    clock.advance(10.0)  # now stable for the full window
    assert tracker.poll() == {tmp_path}


def test_vanished_file_is_dropped(tmp_path: Path) -> None:
    clock = FakeClock()
    tracker = make_tracker(10.0, clock)
    sub = tmp_path / "gone.srt"
    sub.write_text("x", encoding="utf-8")
    tracker.note(sub)
    tracker.poll()

    sub.unlink()
    clock.advance(10.0)
    assert tracker.poll() == set()
    assert tracker.tracked_count == 0


def test_ready_directories_are_deduplicated(tmp_path: Path) -> None:
    clock = FakeClock()
    tracker = make_tracker(10.0, clock)
    one = tmp_path / "one.srt"
    two = tmp_path / "two.srt"
    one.write_text("a", encoding="utf-8")
    two.write_text("b", encoding="utf-8")
    tracker.note(one)
    tracker.note(two)
    tracker.poll()

    clock.advance(10.0)
    # Two settled files in the same directory yield a single directory entry.
    assert tracker.poll() == {tmp_path}


def test_handler_ignores_read_and_delete_events() -> None:
    # Reading files during a scan emits open/close/access events; acting on those
    # would let a scan trigger another scan (issue #27). Deletions leave nothing to
    # process. None of these may reach the tracker.
    noted: list[Path] = []
    handler = _EventHandler(noted.append)
    for event in (
        FileOpenedEvent("/media/movie.srt"),
        FileClosedEvent("/media/movie.srt"),
        FileClosedNoWriteEvent("/media/movie.srt"),
        FileDeletedEvent("/media/movie.srt"),
    ):
        handler.on_any_event(event)
    assert noted == []


def test_handler_notes_mutation_events() -> None:
    # Create, modify, and move are the events that make a file need processing.
    noted: list[Path] = []
    handler = _EventHandler(noted.append)
    handler.on_any_event(FileCreatedEvent("/media/new.srt"))
    handler.on_any_event(FileModifiedEvent("/media/edit.srt"))
    handler.on_any_event(FileMovedEvent("/media/old.srt", "/media/renamed.srt"))
    assert noted == [
        Path("/media/new.srt"),
        Path("/media/edit.srt"),
        Path("/media/renamed.srt"),
    ]


class RecordingWorker:
    def __init__(self) -> None:
        self.requests: list[ScanRequest] = []

    def submit(self, request: ScanRequest, *, queue_if_busy: bool = True) -> int:
        self.requests.append(request)
        return len(self.requests)


class _OneShotTracker:
    """Reports a fixed set of directories on the first poll, then nothing."""

    def __init__(self, directories: set[Path]) -> None:
        self._directories = directories
        self._fired = False

    def poll(self) -> set[Path]:
        if self._fired:
            return set()
        self._fired = True
        return set(self._directories)


def test_poll_loop_submits_scoped_watch_request() -> None:
    worker = RecordingWorker()
    watcher = Watcher(worker, Config, poll_interval=0.01)
    watcher._tracker = _OneShotTracker({Path("/media/movies")})

    thread = threading.Thread(target=watcher._poll_loop, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while not worker.requests:
            if time.monotonic() > deadline:
                raise AssertionError("watcher did not submit a scan")
            time.sleep(0.01)
    finally:
        watcher._stop.set()
        thread.join(timeout=5.0)

    request = worker.requests[0]
    assert request.trigger == "watch"
    assert request.scope == frozenset({Path("/media/movies")})


def test_disabled_watcher_does_not_start(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    config = Config.model_validate(
        {"scan": {"media_paths": [str(media)]}, "watcher": {"enabled": False}}
    )
    worker = RecordingWorker()
    watcher = Watcher(worker, lambda: config)

    watcher.start()
    try:
        # Nothing is observing, so nothing is ever submitted.
        assert watcher._observer is None
    finally:
        watcher.stop()


def _reports(roots: list) -> list[Path]:
    return [root.report for root in roots]


def test_resolve_watch_roots_plain_directories(tmp_path: Path) -> None:
    movies = tmp_path / "movies"
    shows = tmp_path / "shows"
    movies.mkdir()
    shows.mkdir()
    # Without symlinks, the watch roots are exactly the existing media directories, each
    # observed at its own real path.
    roots = resolve_watch_roots([movies, shows])
    assert _reports(roots) == [movies, shows]
    assert [root.observe for root in roots] == [
        Path(os.path.realpath(movies)),
        Path(os.path.realpath(shows)),
    ]


def test_resolve_watch_roots_skips_missing_paths(tmp_path: Path) -> None:
    present = tmp_path / "present"
    present.mkdir()
    missing = tmp_path / "missing"
    assert _reports(resolve_watch_roots([present, missing])) == [present]


def test_resolve_watch_roots_includes_symlinked_tree(tmp_path: Path) -> None:
    # A recursive inotify watch on the root will not descend into a symlinked tree, so
    # the alias is returned as its own watch root, observed at the real target.
    media = tmp_path / "media"
    media.mkdir()
    external = tmp_path / "external"
    (external / "Season 1").mkdir(parents=True)
    link = media / "linked"
    link.symlink_to(external, target_is_directory=True)

    roots = resolve_watch_roots([media])
    assert _reports(roots) == [media, link]
    # The symlinked tree is watched by its real target but reported through the alias.
    assert roots[1].observe == Path(os.path.realpath(external))
    assert roots[1].report == link


def test_resolve_watch_roots_watches_shared_tree_once(tmp_path: Path) -> None:
    # Two symlinks to the same real tree resolve to one identity: only one is watched.
    media = tmp_path / "media"
    media.mkdir()
    target = tmp_path / "external"
    target.mkdir()
    (media / "first").symlink_to(target, target_is_directory=True)
    (media / "second").symlink_to(target, target_is_directory=True)

    roots = resolve_watch_roots([media])
    # Children are visited in sorted order, so the first alias claims the shared identity.
    assert _reports(roots) == [media, media / "first"]


def test_resolve_watch_roots_prunes_symlink_loop(tmp_path: Path) -> None:
    # A symlink pointing back at an ancestor resolves to an already-seen identity.
    media = tmp_path / "media"
    media.mkdir()
    (media / "loop").symlink_to(media, target_is_directory=True)

    assert _reports(resolve_watch_roots([media])) == [media]


def test_resolve_watch_roots_prefers_real_in_tree_path_over_alias(tmp_path: Path) -> None:
    # An alias to a real directory that itself lives under the root defers to the real
    # path, which the root's recursive watch already covers, so no extra watch is added.
    media = tmp_path / "media"
    real = media / "Zreal"
    real.mkdir(parents=True)
    (media / "Aalias").symlink_to(real, target_is_directory=True)

    assert _reports(resolve_watch_roots([media])) == [media]


def test_resolve_watch_roots_follows_nested_symlinks(tmp_path: Path) -> None:
    # A symlinked tree that itself contains a symlink to a second external tree: both
    # alias paths are watched because neither is reachable without crossing a link.
    media = tmp_path / "media"
    media.mkdir()
    outer = tmp_path / "outer"
    outer.mkdir()
    inner = tmp_path / "inner"
    inner.mkdir()
    (media / "outer").symlink_to(outer, target_is_directory=True)
    (outer / "inner").symlink_to(inner, target_is_directory=True)

    roots = resolve_watch_roots([media])
    assert _reports(roots) == [media, media / "outer", media / "outer" / "inner"]
    assert roots[2].observe == Path(os.path.realpath(inner))


def test_event_rewriter_maps_real_paths_to_in_tree_paths() -> None:
    roots = [
        WatchRoot(observe=Path("/media"), report=Path("/media")),
        WatchRoot(observe=Path("/external/show"), report=Path("/media/linked")),
    ]
    rewrite = _make_event_rewriter(roots)
    # A file under a symlinked tree's real target is reported through the alias path.
    assert rewrite(Path("/external/show/s1/ep.srt")) == Path("/media/linked/s1/ep.srt")
    # An exact match on a watched directory maps to that watch's report path.
    assert rewrite(Path("/external/show")) == Path("/media/linked")
    # A plain media root maps to itself.
    assert rewrite(Path("/media/movie/ep.srt")) == Path("/media/movie/ep.srt")
    # A path under no watch is returned unchanged.
    assert rewrite(Path("/elsewhere/ep.srt")) == Path("/elsewhere/ep.srt")


def test_event_rewriter_prefers_the_longest_matching_watch() -> None:
    # A nested watch's longer real prefix wins over the enclosing one it sits inside.
    roots = [
        WatchRoot(observe=Path("/external"), report=Path("/media/linked")),
        WatchRoot(observe=Path("/external/inner"), report=Path("/media/linked/inner")),
    ]
    rewrite = _make_event_rewriter(roots)
    assert rewrite(Path("/external/inner/ep.srt")) == Path("/media/linked/inner/ep.srt")
    assert rewrite(Path("/external/ep.srt")) == Path("/media/linked/ep.srt")


def test_watcher_detects_change_in_symlinked_tree(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    link = media / "linked"
    link.symlink_to(external, target_is_directory=True)

    config = Config.model_validate(
        {
            "scan": {"media_paths": [str(media)]},
            "watcher": {"enabled": True, "stability_window_seconds": 0.2},
        }
    )
    worker = RecordingWorker()
    watcher = Watcher(worker, lambda: config, poll_interval=0.05)

    watcher.start()
    try:
        # A file landing inside the symlinked tree must queue a scoped scan even though
        # the recursive watch on the media root never descends into the link.
        (external / "Movie (2020).en.srt").write_text("1\n", encoding="utf-8")
        deadline = time.monotonic() + 10.0
        while not worker.requests:
            if time.monotonic() > deadline:
                raise AssertionError("watcher never queued a scan for the symlinked tree")
            time.sleep(0.05)
    finally:
        watcher.stop()

    # The scope is reported through the in-tree alias path, matching what a full scan
    # walks, so a watch-triggered scan and a full scan agree on the directory.
    assert worker.requests[0].scope == frozenset({link})


def test_watcher_processes_a_real_file_event(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    config = Config.model_validate(
        {
            "scan": {"media_paths": [str(media)]},
            "watcher": {"enabled": True, "stability_window_seconds": 0.2},
        }
    )
    worker = RecordingWorker()
    watcher = Watcher(worker, lambda: config, poll_interval=0.05)

    watcher.start()
    try:
        # Drop a file in and leave it untouched; once it settles, its directory is
        # queued for a scoped scan through the real inotify path.
        (media / "Movie (2020).en.srt").write_text("1\n", encoding="utf-8")
        deadline = time.monotonic() + 10.0
        while not worker.requests:
            if time.monotonic() > deadline:
                raise AssertionError("watcher never queued a scan for the new file")
            time.sleep(0.05)
    finally:
        watcher.stop()

    request = worker.requests[0]
    assert request.trigger == "watch"
    assert media in request.scope
