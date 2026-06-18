"""The video phase: extract embedded text subtitles and optionally remux.

Run once per video before its subtitle files, and only when extraction is enabled.
It inspects the video's subtitle streams with ffprobe, extracts the wanted text
streams to external SRT files beside the video (image-based streams are left
embedded), and, when remux is enabled, copies the video without the extracted
streams.

The freshly extracted files are returned so the runner feeds them into the normal
subtitle pipeline in the same run; in dry-run nothing is written, so the planned
extractions are reported but no files come back. Every destructive choice follows the
tool's safety rules: extraction and remux write to a temporary file and rename
atomically, a target name that already exists is suffixed rather than overwritten, a
remux verifies free disk space and that the source did not change while ffmpeg ran,
AVI is never remuxed, and the source video is deleted only when explicitly opted in.

An ffmpeg crash or a file I/O failure (an unwritable target directory, a failed
temp-file create, rename, or cleanup) during extraction or remux is recorded as a
warning on this video's result and the scan continues with the rest of the library;
it never escapes to fail the whole job.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from subtitle_tool.pipeline import ffmpeg
from subtitle_tool.pipeline.langcodes import iso639_2_to_1
from subtitle_tool.pipeline.models import Action, ActionType, FileResult
from subtitle_tool.pipeline.safety import resolve_collision

if TYPE_CHECKING:
    from subtitle_tool.config.models import Config, ExtractionConfig


def process_video(
    video: Path, config: Config, dry_run: bool, probe: ffmpeg.MediaProbe | None = None
) -> tuple[FileResult | None, list[Path]]:
    """Extract (and optionally remux) ``video``; return its result and new subtitles.

    Returns ``(result, extracted)``. ``result`` is ``None`` when extraction is
    disabled or there was nothing to do and nothing to warn about, so a clean rescan
    stays inert and reports no video row. ``extracted`` lists the SRT files written
    this run for the runner to process; it is empty in dry-run.

    ``probe`` is the run-wide :class:`~subtitle_tool.pipeline.ffmpeg.MediaProbe` cache;
    the runner passes a shared instance so this video's subtitle-stream probe is reused
    by later sync checks. A standalone call (e.g. the CLI or a test) may omit it and a
    fresh, single-use cache is created.
    """
    extraction = config.extraction
    if not extraction.enabled:
        return None, []
    if probe is None:
        probe = ffmpeg.MediaProbe()

    try:
        streams = probe.subtitle_streams(video)
    except ffmpeg.FfmpegError as exc:
        return FileResult(
            source=video, target=video, error=f"could not inspect {video.name}: {exc}"
        ), []

    wanted = [s for s in streams if s.is_text and _is_wanted(s, extraction.languages)]
    if not wanted:
        return None, []

    actions: list[Action] = []
    warnings: list[str] = []
    extracted: list[Path] = []
    drop_indices: list[int] = []
    planned: set[Path] = set()

    for stream in wanted:
        label = stream.language or "und"
        if dry_run:
            target = resolve_collision(_extracted_name(video, stream), planned)
            planned.add(target)
            actions.append(
                Action(
                    ActionType.EXTRACT_SUBTITLE,
                    f"extract stream {stream.index} ({label}) to {target.name}",
                )
            )
            drop_indices.append(stream.index)
            continue
        try:
            written = _extract(video, stream)
        except (ffmpeg.FfmpegError, OSError) as exc:
            # An ffmpeg crash or a file I/O failure (an unwritable target directory, a
            # failed temp-file create/rename/cleanup) is recorded against this video and
            # the run continues; only a failure that dooms the whole run is job-level.
            warnings.append(f"could not extract stream {stream.index} from {video.name}: {exc}")
            continue
        actions.append(
            Action(
                ActionType.EXTRACT_SUBTITLE,
                f"extract stream {stream.index} ({label}) to {written.name}",
            )
        )
        extracted.append(written)
        drop_indices.append(stream.index)

    if extraction.remux and drop_indices:
        _remux(video, drop_indices, extraction, dry_run, actions, warnings)

    if not actions and not warnings:
        return None, extracted
    return FileResult(source=video, target=video, actions=actions, warnings=warnings), extracted


def _is_wanted(stream: ffmpeg.SubtitleStream, languages: list[str]) -> bool:
    """Whether ``stream`` should be extracted given the configured language filter.

    An empty filter extracts every text stream. With a filter set, a stream is wanted
    only when its language maps to a configured code; an untagged or unmappable stream
    is left embedded rather than guessed at.
    """
    if not languages:
        return True
    code = iso639_2_to_1(stream.language)
    return code is not None and code in languages


def _extracted_name(video: Path, stream: ffmpeg.SubtitleStream) -> Path:
    """The desired (pre-collision) external SRT path for ``stream``."""
    code = iso639_2_to_1(stream.language)
    name = f"{video.stem}.{code}.srt" if code else f"{video.stem}.srt"
    return video.with_name(name)


def _extract(video: Path, stream: ffmpeg.SubtitleStream) -> Path:
    """Extract ``stream`` to a temp file and rename it atomically into place."""
    target = resolve_collision(_extracted_name(video, stream))
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".srt")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        ffmpeg.extract_subtitle(video, stream.index, tmp)
        # Resolve once more at the last moment so a file that appeared during extraction
        # is not clobbered, then swap the result in atomically.
        final = resolve_collision(target)
        tmp.replace(final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return final


def _remux(
    video: Path,
    drop_indices: list[int],
    extraction: ExtractionConfig,
    dry_run: bool,
    actions: list[Action],
    warnings: list[str],
) -> None:
    """Remux ``video`` without ``drop_indices``, recording the outcome.

    With ``delete_original_video`` the remuxed copy atomically replaces the source.
    Otherwise the original is kept and the result is written beside it, since deleting
    the source video is opt-in and off by default. Any safety check that fails leaves
    the original untouched and records a warning.
    """
    if video.suffix.lower() == ".avi":
        warnings.append(f"not remuxing {video.name}: AVI containers are not remuxed")
        return

    if dry_run:
        actions.append(
            Action(ActionType.REMUX, f"remux to drop {len(drop_indices)} extracted stream(s)")
        )
        if extraction.delete_original_video:
            actions.append(
                Action(
                    ActionType.DELETE_ORIGINAL, f"replace original {video.name} with remuxed video"
                )
            )
        return

    try:
        before = video.stat()
    except OSError as exc:
        warnings.append(f"could not stat {video.name} before remux: {exc}")
        return

    free = shutil.disk_usage(video.parent).free
    if free < before.st_size:
        warnings.append(
            f"not enough free disk space to remux {video.name} "
            f"(need ~{before.st_size} bytes, {free} free)"
        )
        return

    fd, tmp_name = tempfile.mkstemp(
        dir=video.parent, prefix=f".{video.name}.remux.", suffix=video.suffix
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        ffmpeg.remux_without_streams(video, drop_indices, tmp)
    except ffmpeg.FfmpegError as exc:
        tmp.unlink(missing_ok=True)
        warnings.append(f"remux failed, left {video.name} untouched: {exc}")
        return

    if not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        warnings.append(f"remux produced no output, left {video.name} untouched")
        return

    after = video.stat()
    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        tmp.unlink(missing_ok=True)
        warnings.append(f"{video.name} changed during remux; discarded remuxed result")
        return

    if extraction.delete_original_video:
        tmp.replace(video)
        actions.append(
            Action(
                ActionType.REMUX,
                f"remux {video.name} dropping {len(drop_indices)} extracted stream(s)",
            )
        )
        actions.append(
            Action(ActionType.DELETE_ORIGINAL, f"replaced original {video.name} with remuxed video")
        )
    else:
        final = resolve_collision(video.with_name(f"{video.stem}.remuxed{video.suffix}"))
        tmp.replace(final)
        actions.append(
            Action(ActionType.REMUX, f"remux {video.name} to {final.name}, kept original")
        )
