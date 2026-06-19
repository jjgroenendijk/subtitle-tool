"""Tests for the shared real-directory identity helper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_tool.fs_identity import real_key

if TYPE_CHECKING:
    from pathlib import Path


def test_real_key_is_stable_for_one_directory(tmp_path: Path) -> None:
    assert real_key(tmp_path) == real_key(tmp_path)


def test_real_key_matches_through_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(target, target_is_directory=True)
    # Stat'ing through the link yields the target's identity, so two links to one tree
    # resolve to a single key.
    assert real_key(link) == real_key(target)


def test_real_key_distinguishes_separate_directories(tmp_path: Path) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    assert real_key(one) != real_key(two)


def test_real_key_is_none_for_unstattable_path(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.symlink_to(tmp_path / "does-not-exist", target_is_directory=True)
    assert real_key(broken) is None
