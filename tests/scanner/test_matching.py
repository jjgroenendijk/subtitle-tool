"""Tests for the subtitle-to-video matching rules."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.scanner.matching import find_video


def test_exact_match() -> None:
    videos = [Path("Movie (2020).mkv"), Path("Other (2019).mkv")]

    video, ambiguous = find_video("Movie (2020)", videos)

    assert video == Path("Movie (2020).mkv")
    assert ambiguous is False


def test_no_match_returns_none() -> None:
    videos = [Path("Movie (2020).mkv")]

    video, ambiguous = find_video("Totally Different Film", videos)

    assert video is None
    assert ambiguous is False


def test_similarity_match_on_near_identical_name() -> None:
    videos = [Path("The Matrix (1999) 1080p.mkv")]

    video, ambiguous = find_video("The Matrix (1999) 1080p BluRay", videos)

    assert video == videos[0]
    assert ambiguous is False


def test_episode_parsing_matches_differently_named_files() -> None:
    videos = [
        Path("Show - 01x02 - Pilot.mkv"),
        Path("Show - 01x03 - Next.mkv"),
    ]

    video, ambiguous = find_video("Show.S01E02.HDTV", videos)

    assert video == videos[0]
    assert ambiguous is False


def test_year_parsing_matches_movie() -> None:
    videos = [Path("Inception 2010 Remux.mkv"), Path("Tenet 2020.mkv")]

    video, ambiguous = find_video("Inception (2010)", videos)

    assert video == videos[0]
    assert ambiguous is False


def test_ambiguous_exact_match_across_containers() -> None:
    videos = [Path("Movie (2020).mkv"), Path("Movie (2020).mp4")]

    video, ambiguous = find_video("Movie (2020)", videos)

    assert video is None
    assert ambiguous is True


def test_ambiguous_episode_match() -> None:
    videos = [Path("Show 1x02 A.mkv"), Path("Show 1x02 B.mkv")]

    video, ambiguous = find_video("Show.S01E02", videos)

    assert video is None
    assert ambiguous is True
