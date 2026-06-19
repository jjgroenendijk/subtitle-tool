"""Tests for the library view helpers: server-side sorting and pagination."""

from __future__ import annotations

from subtitle_tool.index.models import IndexedVideo, LibraryVideo
from subtitle_tool.web.library_view import MAX_PER_PAGE, paginate, sort_library


def _video(path: str, size: int = 0, mtime: int = 0) -> IndexedVideo:
    return IndexedVideo(
        path=path, size=size, mtime=mtime, first_seen=0, last_seen=0, last_changed=0
    )


def _library(
    path: str, *, size: int = 0, mtime: int = 0, missing: list[str] | None = None
) -> LibraryVideo:
    return LibraryVideo(
        video=_video(path, size=size, mtime=mtime),
        subtitles=[],
        missing_languages=missing or [],
    )


def test_sort_library_sorts_by_name_case_insensitively() -> None:
    videos = [_library("/m/bravo.mkv"), _library("/m/Alpha.mkv")]

    sort, direction = sort_library(videos, "name", "asc")

    assert (sort, direction) == ("name", "asc")
    assert [v.video.path for v in videos] == ["/m/Alpha.mkv", "/m/bravo.mkv"]


def test_sort_library_descending_by_size() -> None:
    videos = [_library("/m/a.mkv", size=10), _library("/m/b.mkv", size=99)]

    sort_library(videos, "size", "desc")

    assert [v.video.size for v in videos] == [99, 10]


def test_sort_library_normalizes_unknown_column_and_direction() -> None:
    videos = [_library("/m/b.mkv"), _library("/m/a.mkv")]

    sort, direction = sort_library(videos, "bogus", "sideways")

    # Falls back to the default name/asc sort rather than erroring on bad input.
    assert (sort, direction) == ("name", "asc")
    assert [v.video.path for v in videos] == ["/m/a.mkv", "/m/b.mkv"]


def test_paginate_slices_and_reports_metadata() -> None:
    videos = [_library(f"/m/{i}.mkv") for i in range(5)]

    page, pagination = paginate(videos, page=2, per_page=2, missing=False)

    assert [v.video.path for v in page] == ["/m/2.mkv", "/m/3.mkv"]
    assert pagination == {
        "page": 2,
        "per_page": 2,
        "total_pages": 3,
        "total": 5,
        "missing": False,
    }


def test_paginate_clamps_out_of_range_page() -> None:
    videos = [_library(f"/m/{i}.mkv") for i in range(3)]

    page, pagination = paginate(videos, page=99, per_page=1, missing=True)

    assert [v.video.path for v in page] == ["/m/2.mkv"]
    assert pagination["page"] == 3
    assert pagination["missing"] is True


def test_paginate_caps_per_page() -> None:
    videos = [_library("/m/a.mkv")]

    _page, pagination = paginate(videos, page=1, per_page=10_000, missing=False)

    assert pagination["per_page"] == MAX_PER_PAGE
