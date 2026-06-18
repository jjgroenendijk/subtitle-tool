"""Subtitle-to-video matching.

External subtitles follow the convention ``<video basename>[.lang][.flags].ext``
(for example ``Movie (2020).en.sdh.srt``). The matcher recovers the intended video
basename by peeling recognised language and flag tokens off the subtitle name, then
pairs it with a video in the same directory using a fixed sequence of rules:

1. exact basename match,
2. normalised basename similarity,
3. season/episode (TV) or movie/year parsing.

The rules are tried in order; the first that yields exactly one candidate wins. A
rule that yields more than one candidate is ambiguous: matching stops and the
subtitle is left standalone with a warning. Nothing is ever guessed.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Recognised trailing tokens on a subtitle filename. Flags describe the subtitle
# variant; a language token is a two- or three-letter code. Both are peeled off the
# name to recover the video basename the subtitle belongs to.
_FLAG_TOKENS = frozenset({"forced", "sdh", "hi", "cc", "foreign", "default"})
_LANGUAGE_TOKEN = re.compile(r"^[a-z]{2,3}$")

# Minimum normalised-name similarity for rule 2. High enough that only near-identical
# names match, leaving genuinely different names to the episode/year rules.
_SIMILARITY_THRESHOLD = 0.85

_EPISODE = re.compile(r"s(\d{1,2})\s*e(\d{1,2})|(\d{1,2})x(\d{2})", re.IGNORECASE)
_YEAR = re.compile(r"(?:19|20)\d{2}")


def split_subtitle_name(path: Path) -> tuple[str, str | None, list[str]]:
    """Split a subtitle filename into its video basename, language, and flags.

    Peels recognised flag tokens (right to left) and then a single language token off
    the stem. The remaining left-hand portion is the video basename the subtitle is
    expected to share. A token is only peeled while something is left to its left, so
    a bare ``en.srt`` keeps ``en`` as its basename rather than emptying it.
    """
    parts = path.name[: -len(path.suffix)].split(".") if path.suffix else path.name.split(".")
    flags: list[str] = []
    while len(parts) > 1 and parts[-1].lower() in _FLAG_TOKENS:
        flags.insert(0, parts.pop().lower())
    language: str | None = None
    if len(parts) > 1 and _LANGUAGE_TOKEN.match(parts[-1].lower()):
        language = parts.pop().lower()
    return ".".join(parts), language, flags


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _parse_episode(name: str) -> tuple[int, int] | None:
    match = _EPISODE.search(name)
    if not match:
        return None
    if match.group(1) is not None:
        return int(match.group(1)), int(match.group(2))
    return int(match.group(3)), int(match.group(4))


def _parse_year(name: str) -> int | None:
    match = _YEAR.search(name)
    return int(match.group()) if match else None


def find_video(base: str, videos: list[Path]) -> tuple[Path | None, bool]:
    """Find the video a subtitle basename belongs to among ``videos``.

    Returns ``(video, ambiguous)``. ``video`` is the matched video or ``None``;
    ``ambiguous`` is true when a rule produced more than one equally good candidate,
    in which case the caller should leave the subtitle standalone with a warning.
    Rules are applied in order and the first to produce candidates decides the
    outcome, so a clean exact match is never overridden by a fuzzier rule.
    """
    for candidates in (
        _exact_candidates(base, videos),
        _similarity_candidates(base, videos),
        _episode_or_year_candidates(base, videos),
    ):
        if len(candidates) == 1:
            return candidates[0], False
        if len(candidates) > 1:
            return None, True
    return None, False


def _exact_candidates(base: str, videos: list[Path]) -> list[Path]:
    return [video for video in videos if video.stem == base]


def _similarity_candidates(base: str, videos: list[Path]) -> list[Path]:
    target = _normalize(base)
    if not target:
        return []
    scored = [
        (SequenceMatcher(None, target, _normalize(video.stem)).ratio(), video) for video in videos
    ]
    best = max((ratio for ratio, _ in scored), default=0.0)
    if best < _SIMILARITY_THRESHOLD:
        return []
    return [video for ratio, video in scored if ratio == best]


def _episode_or_year_candidates(base: str, videos: list[Path]) -> list[Path]:
    episode = _parse_episode(base)
    if episode is not None:
        return [video for video in videos if _parse_episode(video.stem) == episode]
    year = _parse_year(base)
    if year is not None:
        return [video for video in videos if _parse_year(video.stem) == year]
    return []
