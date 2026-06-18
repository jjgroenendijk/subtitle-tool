"""Tests for the SQLite media index and its scan reconciliation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from subtitle_tool.index import IndexStore
from subtitle_tool.scanner import scan_paths

if TYPE_CHECKING:
    from subtitle_tool.scanner.models import ScanResult


def make_store(tmp_path: Path) -> IndexStore:
    return IndexStore(tmp_path / "index.db")


def write_subtitle(path: Path, text: str = "hello") -> None:
    path.write_text(
        f"1\n00:00:01,000 --> 00:00:04,000\n{text}\n",
        encoding="utf-8",
    )


def build_library(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    write_subtitle(root / "Movie (2020).en.srt")


def scan(root: Path) -> ScanResult:
    return scan_paths([str(root)], [])


def test_new_files_are_inserted_and_processed(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    store = make_store(tmp_path)

    result = store.reconcile(scan(media))

    video = media / "Movie (2020).mkv"
    subtitle = media / "Movie (2020).en.srt"
    assert result.new == {video, subtitle}
    assert result.process_paths == {video, subtitle}
    assert result.unchanged == set()
    # The rows are now queryable through the library view.
    library = store.library()
    assert [entry.video.path for entry in library] == [str(video)]
    assert [sub.path for sub in library[0].subtitles] == [str(subtitle)]


def test_unchanged_files_are_skipped_on_a_second_scan(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    store = make_store(tmp_path)

    store.reconcile(scan(media))
    second = store.reconcile(scan(media))

    video = media / "Movie (2020).mkv"
    subtitle = media / "Movie (2020).en.srt"
    assert second.unchanged == {video, subtitle}
    assert second.process_paths == set()
    assert second.new == set()


def test_changed_file_is_reprocessed(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    store = make_store(tmp_path)
    store.reconcile(scan(media))

    # Rewrite the subtitle with new content and a newer mtime: a changed fingerprint.
    subtitle = media / "Movie (2020).en.srt"
    write_subtitle(subtitle, "different and noticeably longer content here")
    future = subtitle.stat().st_mtime + 10
    os.utime(subtitle, (future, future))

    result = store.reconcile(scan(media))

    assert subtitle in result.changed
    assert subtitle in result.process_paths
    # The untouched video is still skipped.
    assert (media / "Movie (2020).mkv") in result.unchanged


def test_mtime_only_change_is_reprocessed(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    store = make_store(tmp_path)
    store.reconcile(scan(media))

    subtitle = media / "Movie (2020).en.srt"
    future = subtitle.stat().st_mtime + 10
    os.utime(subtitle, (future, future))

    result = store.reconcile(scan(media))

    assert subtitle in result.changed


def test_removed_file_is_marked_gone(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    store = make_store(tmp_path)
    store.reconcile(scan(media))

    subtitle = media / "Movie (2020).en.srt"
    subtitle.unlink()

    result = store.reconcile(scan(media))

    assert subtitle in result.gone
    # A gone subtitle no longer appears in the library coverage.
    library = store.library()
    assert library[0].subtitles == []
    # The removal is recorded in the audit history.
    events = [(entry.event, Path(entry.path)) for entry in store.history()]
    assert ("gone", subtitle) in events


def test_scoped_scan_does_not_mark_files_outside_scope_gone(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media / "A")
    build_library(media / "B")
    store = make_store(tmp_path)
    store.reconcile(scan(media))

    # A scoped scan of only B; A's files are absent from this inventory but out of
    # scope, so they must not be marked gone.
    scoped = scan_paths([str(media / "B")], [])
    result = store.reconcile(scoped, scope=frozenset({media / "B"}))

    assert result.gone == set()
    assert all(not entry.video.gone for entry in store.library())


def test_non_recursive_scope_spares_files_in_subdirectories(tmp_path: Path) -> None:
    # A directory whose files were indexed, plus a subtitle in a nested subdirectory.
    # A non-recursive scan of the parent never looks in the subdirectory, so reconcile
    # with recursive=False must not judge the nested file gone just because it is
    # absent from the shallow inventory.
    media = tmp_path / "media"
    build_library(media)
    nested = media / "Extras"
    nested.mkdir()
    (nested / "Bonus (2020).mkv").write_text("video", encoding="utf-8")
    nested_subtitle = nested / "Bonus (2020).en.srt"
    write_subtitle(nested_subtitle)
    store = make_store(tmp_path)
    store.reconcile(scan(media))  # full recursive scan indexes the nested file too

    # Re-scan only the top level of media, non-recursively, after the top-level
    # subtitle changed; the nested file is untouched and unseen.
    write_subtitle(media / "Movie (2020).en.srt", text="changed")
    shallow = scan_paths([str(media)], [], recursive=False)
    result = store.reconcile(shallow, scope=frozenset({media}), recursive=False)

    assert nested_subtitle not in result.gone
    assert result.gone == set()
    indexed = {Path(s.path) for entry in store.library() for s in entry.subtitles}
    assert nested_subtitle in indexed


def test_recursive_scope_still_marks_subdirectory_files_gone(tmp_path: Path) -> None:
    # A full (recursive) scope keeps the conservative behaviour: a file that genuinely
    # vanished from a scanned subtree is marked gone, so the non-recursive path is the
    # only one that spares nested files.
    media = tmp_path / "media"
    build_library(media)
    nested = media / "Extras"
    nested.mkdir()
    nested_subtitle = nested / "Bonus (2020).en.srt"
    write_subtitle(nested_subtitle)
    store = make_store(tmp_path)
    store.reconcile(scan(media))

    nested_subtitle.unlink()
    result = store.reconcile(scan(media), scope=frozenset({media}))

    assert nested_subtitle in result.gone


def test_missing_wanted_language_reporting(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    write_subtitle(media / "Movie (2020).en.srt")
    store = make_store(tmp_path)
    store.reconcile(scan(media))

    library = store.library(["en", "nl", "de"])

    assert len(library) == 1
    entry = library[0]
    assert entry.languages == ["en"]
    assert entry.missing_languages == ["nl", "de"]


def test_dry_run_reconcile_does_not_persist(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    store = make_store(tmp_path)

    result = store.reconcile(scan(media), dry_run=True)

    # Classification still happens so a dry run skips unchanged files...
    assert result.process_paths
    # ...but nothing was written: the index stays empty.
    assert store.library() == []
    assert store.history() == []


def test_index_is_rebuildable_from_a_full_scan(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    db = tmp_path / "index.db"

    first = IndexStore(db)
    first.reconcile(scan(media))
    first.close()
    db.unlink()

    rebuilt = IndexStore(db)
    result = rebuilt.reconcile(scan(media))

    # With a fresh index every file is new again, repopulating the library.
    assert result.new == {media / "Movie (2020).mkv", media / "Movie (2020).en.srt"}
    assert len(rebuilt.library()) == 1


def test_reset_clears_rows_so_a_scan_reprocesses_everything(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    store = make_store(tmp_path)
    store.reconcile(scan(media))

    store.reset()

    # No rows remain, so the library is empty and the connection still works.
    assert store.library() == []
    # A scan over the unchanged files now treats every one as new again.
    result = store.reconcile(scan(media))
    assert result.new == {media / "Movie (2020).mkv", media / "Movie (2020).en.srt"}
    assert len(store.library()) == 1


def test_subtitle_flags_are_parsed_and_stored(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    write_subtitle(media / "Movie (2020).en.forced.srt")
    store = make_store(tmp_path)
    store.reconcile(scan(media))

    subtitle = store.library()[0].subtitles[0]
    assert subtitle.language == "en"
    assert subtitle.flags == ["forced"]
    assert subtitle.matched is True


def test_classification_does_not_query_per_file(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    # A library large enough that a per-file SELECT would be visible in the count.
    for n in range(25):
        (media / f"Movie {n}.mkv").write_text("video", encoding="utf-8")
        write_subtitle(media / f"Movie {n}.en.srt")
    store = make_store(tmp_path)

    counter = _ExecuteCounter(store._conn)
    store._conn = counter  # type: ignore[assignment]
    result = store.reconcile(scan(media))

    assert len(result.new) == 50  # 25 videos + 25 subtitles all discovered
    # Existing rows are loaded with two bulk SELECTs (videos, subtitles); the writes go
    # through executemany. So the single-statement query count stays constant, not one
    # per discovered file.
    assert counter.execute_calls == 2


def test_reappeared_file_is_treated_as_changed(tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    store = make_store(tmp_path)
    store.reconcile(scan(media))

    subtitle = media / "Movie (2020).en.srt"
    subtitle.unlink()
    store.reconcile(scan(media))  # marks it gone
    write_subtitle(subtitle)

    result = store.reconcile(scan(media))

    assert subtitle in result.changed
    # It is present in the library again, not gone.
    assert [sub.path for sub in store.library()[0].subtitles] == [str(subtitle)]


class _ExecuteCounter:
    """A sqlite connection proxy that counts single-statement ``execute`` calls.

    ``executemany`` and everything else delegate straight through, so the count
    isolates per-row query overhead from the batched writes.
    """

    def __init__(self, conn) -> None:
        self._conn = conn
        self.execute_calls = 0

    def execute(self, *args, **kwargs):
        self.execute_calls += 1
        return self._conn.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)
