"""Scan orchestration: from media paths to an inventory.

Walks the configured media paths, classifies files, and pairs subtitles with
videos. Matching is scoped to a single directory: external subtitles live beside
their video (or are dropped there), which is what Plex expects, and per-directory
scoping keeps matching simple and avoids spurious cross-directory ambiguity.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from subtitle_tool.scanner.matching import find_video, split_subtitle_name
from subtitle_tool.scanner.models import (
    MatchWarning,
    ScanResult,
    StandaloneSubtitle,
    VideoGroup,
    WarningReason,
)
from subtitle_tool.scanner.walk import is_subtitle, is_video, iter_files

if TYPE_CHECKING:
    from subtitle_tool.config.models import Config


def scan(config: Config) -> ScanResult:
    """Scan the media paths in ``config`` and return the inventory."""
    return scan_paths(config.scan.media_paths, config.scan.exclude_patterns)


def scan_paths(
    media_paths: list[str], exclude_patterns: list[str], *, recursive: bool = True
) -> ScanResult:
    """Scan ``media_paths`` and return the inventory.

    Files are discovered across all roots, deduplicated by absolute path (so
    overlapping roots do not double-count), then grouped by directory for matching.

    ``recursive=False`` walks only the files directly in each root, not their
    subtrees. The watcher passes its changed directories this way so a scoped scan
    does not re-walk a large library; the gone-marking in
    :meth:`~subtitle_tool.index.store.IndexStore.reconcile` must use the matching
    ``recursive`` flag so files in unscanned subdirectories are never judged gone.
    """
    videos_by_dir: dict[Path, list[Path]] = defaultdict(list)
    subtitles_by_dir: dict[Path, list[Path]] = defaultdict(list)
    seen: set[Path] = set()

    for root in media_paths:
        for path in iter_files(Path(root), exclude_patterns, recursive=recursive):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if is_video(path):
                videos_by_dir[path.parent].append(path)
            elif is_subtitle(path):
                subtitles_by_dir[path.parent].append(path)

    video_groups: list[VideoGroup] = []
    standalone_subtitles: list[StandaloneSubtitle] = []

    for directory in sorted(videos_by_dir.keys() | subtitles_by_dir.keys()):
        videos = videos_by_dir.get(directory, [])
        subtitles = subtitles_by_dir.get(directory, [])
        matched, standalone = _match_directory(videos, subtitles)
        video_groups.extend(matched)
        standalone_subtitles.extend(standalone)

    return ScanResult(
        video_groups=video_groups,
        standalone_subtitles=standalone_subtitles,
    )


def _match_directory(
    videos: list[Path], subtitles: list[Path]
) -> tuple[list[VideoGroup], list[StandaloneSubtitle]]:
    """Pair each subtitle in a directory with one of its videos."""
    paired: dict[Path, list[Path]] = {video: [] for video in videos}
    standalone: list[StandaloneSubtitle] = []

    for subtitle in subtitles:
        base, _language, _flags = split_subtitle_name(subtitle)
        video, ambiguous = find_video(base, videos)
        if video is not None:
            paired[video].append(subtitle)
        elif ambiguous:
            standalone.append(
                StandaloneSubtitle(
                    subtitle=subtitle,
                    warnings=[
                        MatchWarning(
                            reason=WarningReason.AMBIGUOUS_MATCH,
                            message=(
                                f"{subtitle.name} matches more than one video in "
                                f"{subtitle.parent}; leaving it standalone"
                            ),
                            subtitle=subtitle,
                        )
                    ],
                )
            )
        else:
            standalone.append(
                StandaloneSubtitle(
                    subtitle=subtitle,
                    warnings=[
                        MatchWarning(
                            reason=WarningReason.NO_MATCH,
                            message=f"no video in {subtitle.parent} matches {subtitle.name}",
                            subtitle=subtitle,
                        )
                    ],
                )
            )

    groups = [
        VideoGroup(video=video, subtitles=sorted(subs)) for video, subs in sorted(paired.items())
    ]
    return groups, standalone
