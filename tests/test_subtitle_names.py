"""Tests for shared subtitle filename parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from subtitle_tool.subtitle_names import split_subtitle_name


@pytest.mark.parametrize(
    ("name", "base", "language", "flags"),
    [
        ("Movie (2020).srt", "Movie (2020)", None, []),
        ("Movie (2020).en.srt", "Movie (2020)", "en", []),
        ("Movie (2020).en.sdh.srt", "Movie (2020)", "en", ["sdh"]),
        ("Movie (2020).en.forced.srt", "Movie (2020)", "en", ["forced"]),
        ("Movie (2020).forced.srt", "Movie (2020)", None, ["forced"]),
        ("Show.S01E02.eng.srt", "Show.S01E02", "eng", []),
        # A bare language code keeps its name rather than peeling to nothing.
        ("en.srt", "en", None, []),
        # Dotted release names keep their structure; only trailing tokens are peeled.
        ("Movie.2020.1080p.BluRay.en.srt", "Movie.2020.1080p.BluRay", "en", []),
    ],
)
def test_split_subtitle_name(name: str, base: str, language: str | None, flags: list[str]) -> None:
    assert split_subtitle_name(Path(name)) == (base, language, flags)
