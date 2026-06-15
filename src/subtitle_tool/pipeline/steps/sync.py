"""Sync step: correct an out-of-sync subtitle against the video's audio.

Runs only for a subtitle matched to a video, only on SRT content, and only when
enabled. It hands the current text and the video to ffsubsync, which measures the
time shift that best aligns the subtitle's speech to the audio, and applies that
shift only when the result is trustworthy: the measured shift exceeds the configured
minimum (smaller shifts are treated as already in sync), the alignment score clears
the acceptance threshold, and the absolute shift stays under the safety cap. Any other
outcome -- a shift over the cap, a low score, a timeout, a video without audio, or an
ffsubsync failure -- keeps the original timings and records a warning, so a wrong
guess can never desync a subtitle that was fine.

ffsubsync works on files, so the step writes the in-memory text to a temporary SRT,
runs the alignment to a second temporary file, and reads the shifted result back into
the work item; the runner's commit then writes it like any other change. In dry-run
the measurement still runs (the decision must match a real run) but the text is left
untouched.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline import ffmpeg, sync
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.workitem import WorkItem


def correct_sync(
    item: WorkItem,
    config: Config,
    *,
    dry_run: bool,
    probe: ffmpeg.MediaProbe | None = None,
) -> None:
    """Shift ``item``'s timings to match its video when ffsubsync is confident.

    ``probe`` is the run-wide :class:`~subtitle_tool.pipeline.ffmpeg.MediaProbe` cache:
    the runner passes a shared instance so a video matched by several subtitles is
    probed for its audio stream once, not once per subtitle. A standalone call may omit
    it and a fresh, single-use cache is created.
    """
    settings = config.sync
    if not settings.enabled or item.video is None:
        return
    # ffsubsync reads and writes SRT; non-SRT content (e.g. an un-converted ASS file)
    # is left to a future run once conversion has produced an SRT to align.
    if item.target.suffix.lower() != ".srt":
        return
    if probe is None:
        probe = ffmpeg.MediaProbe()

    try:
        if not probe.has_audio_stream(item.video):
            item.warn(f"not correcting sync: {item.video.name} has no audio track")
            return
    except ffmpeg.FfmpegError as exc:
        item.warn(f"not correcting sync: could not inspect {item.video.name}: {exc}")
        return

    try:
        offset_seconds, score, text = _measure(
            item, settings.max_offset_seconds, settings.timeout_seconds
        )
    except sync.SyncTimeout as exc:
        item.warn(f"sync correction skipped: {exc}")
        return
    except sync.SyncError as exc:
        item.warn(f"sync correction skipped: {exc}")
        return

    shift = abs(offset_seconds)
    if shift < settings.min_offset_seconds:
        # Already in sync within the configured tolerance: nothing to do, no warning.
        return
    if score < settings.min_score:
        item.warn(
            f"sync correction not applied: alignment score {score:.3f} below "
            f"threshold {settings.min_score:g}; kept original timings"
        )
        return
    if shift > settings.max_offset_seconds:
        item.warn(
            f"sync correction not applied: shift {offset_seconds:+.3f}s exceeds "
            f"cap {settings.max_offset_seconds:g}s; kept original timings"
        )
        return

    if not dry_run:
        item.text = text
    item.record(
        ActionType.SYNC_CORRECT,
        f"shift timings by {offset_seconds:+.3f}s (score {score:.3f})",
    )


def _measure(
    item: WorkItem, max_offset_seconds: float, timeout_seconds: float
) -> tuple[float, float, str]:
    """Run ffsubsync on a temp copy of ``item``'s text; return offset, score, and text."""
    assert item.video is not None  # guarded by the caller
    in_path = _write_temp(item, item.text)
    out_fd, out_name = tempfile.mkstemp(
        dir=item.target.parent, prefix=f".{item.target.name}.synced.", suffix=".srt"
    )
    os.close(out_fd)
    out_path = Path(out_name)
    # ffsubsync writes its own output; remove the empty placeholder so a run that
    # declines to write leaves no file and is detected as a failure.
    out_path.unlink(missing_ok=True)
    try:
        result = sync.synchronize(
            item.video,
            in_path,
            out_path,
            max_offset_seconds=max_offset_seconds,
            timeout_seconds=timeout_seconds,
        )
        return result.offset_seconds, result.score, result.output.read_text(encoding="utf-8")
    finally:
        in_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)


def _write_temp(item: WorkItem, text: str) -> Path:
    """Write ``text`` to a temp SRT beside the target for ffsubsync to read."""
    fd, name = tempfile.mkstemp(
        dir=item.target.parent, prefix=f".{item.target.name}.tosync.", suffix=".srt"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)
