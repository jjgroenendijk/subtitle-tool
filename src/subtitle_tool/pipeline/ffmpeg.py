"""Thin wrappers around ffprobe and ffmpeg for the video phase.

Three operations: inspect a video's subtitle streams, extract one text stream to an
external SRT, and remux a video dropping a set of streams. Each shells out to the
bundled ffprobe/ffmpeg binaries and turns any failure — a missing binary, a non-zero
exit, unparseable output, or a command that runs past its time budget — into a single
:class:`FfmpegError` the caller handles, so one bad video never crashes or wedges a
run. Orchestration (collision handling, disk-space and stability checks, dry-run,
atomic replace) lives in :mod:`subtitle_tool.pipeline.video`; this module only runs
commands.

Every invocation is bounded by a timeout so a corrupt or stalled media file cannot
hang the single worker indefinitely. Defaults are conservative: probing reads only
container metadata and should return in seconds, while extraction and the
stream-copy remux are I/O bound and given far more headroom so a large but healthy
file still completes. :class:`MediaProbe` memoises the two read-only probes for the
length of one pipeline run, so a video with several matched subtitles is inspected
once rather than once per subtitle.
"""

from __future__ import annotations

import itertools
import json
import logging
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from subtitle_tool.pipeline.stream_variants import SubtitleVariant, classify_variant

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"

# Bounds on each subprocess so one bad file cannot wedge the worker. Probing reads
# container metadata only, so a healthy file returns near-instantly and a minute is
# already generous; extraction and remux move stream data and are given far more room
# so a large but healthy file is never killed mid-copy.
PROBE_TIMEOUT_SECONDS = 60.0
EXTRACT_TIMEOUT_SECONDS = 600.0
REMUX_TIMEOUT_SECONDS = 3600.0

# Subtitle codecs ffprobe reports that carry text we can extract to SRT. Image-based
# formats (PGS, VOBSUB/DVD, XSUB) are deliberately absent: they cannot become text
# without OCR, so they are left embedded.
TEXT_CODECS = frozenset(
    {
        "subrip",
        "srt",
        "ass",
        "ssa",
        "mov_text",
        "webvtt",
        "text",
        "subviewer",
        "subviewer1",
        "microdvd",
        "mpl2",
        "pjs",
        "jacosub",
        "sami",
        "realtext",
        "stl",
        "vplayer",
    }
)


class FfmpegError(Exception):
    """An ffprobe/ffmpeg invocation failed or its output could not be understood."""


class FfmpegTimeoutError(FfmpegError):
    """An ffprobe/ffmpeg invocation exceeded its time budget and was killed.

    A subclass of :class:`FfmpegError` so every caller that already tolerates a probe
    or command failure also tolerates a timeout: the file is reported with a warning
    and the run continues.
    """


@dataclass(frozen=True)
class SubtitleStream:
    """One subtitle stream found in a video, as reported by ffprobe."""

    index: int
    codec: str
    language: str | None = None
    variant: SubtitleVariant = SubtitleVariant.NORMAL

    @property
    def is_text(self) -> bool:
        """Whether this stream is a text format that can be extracted to SRT."""
        return self.codec in TEXT_CODECS


def probe_subtitle_streams(video: Path) -> list[SubtitleStream]:
    """Return the subtitle streams in ``video`` (text and image alike)."""
    proc = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index,codec_name:stream_disposition:stream_tags=language,title",
            "-of",
            "json",
            str(video),
        ],
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FfmpegError(f"could not parse ffprobe output: {exc}") from exc

    streams: list[SubtitleStream] = []
    for raw in data.get("streams", []):
        index = raw.get("index")
        codec = raw.get("codec_name")
        if index is None or codec is None:
            continue
        tags = raw.get("tags") or {}
        language = tags.get("language")
        language = language.lower() if language else None
        if language in {"", "und"}:
            language = None
        variant = classify_variant(raw.get("disposition"), tags.get("title"))
        streams.append(
            SubtitleStream(
                index=int(index),
                codec=str(codec).lower(),
                language=language,
                variant=variant,
            )
        )
    return streams


def has_audio_stream(video: Path) -> bool:
    """Whether ``video`` carries at least one audio stream.

    Sync correction aligns a subtitle to the video's speech, so a video with no
    audio track has nothing to align against and the correction is skipped.
    """
    proc = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "json",
            str(video),
        ],
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FfmpegError(f"could not parse ffprobe output: {exc}") from exc
    return bool(data.get("streams"))


def extract_subtitle(video: Path, stream_index: int, target: Path) -> None:
    """Extract the stream at ``stream_index`` from ``video`` to ``target`` as SRT."""
    _run(
        [
            FFMPEG,
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-map",
            f"0:{stream_index}",
            "-c:s",
            "srt",
            str(target),
        ],
        timeout=EXTRACT_TIMEOUT_SECONDS,
    )


def remux_without_streams(video: Path, drop_indices: list[int], target: Path) -> None:
    """Copy ``video`` to ``target`` keeping every stream except ``drop_indices``."""
    args = [FFMPEG, "-nostdin", "-y", "-v", "error", "-i", str(video), "-map", "0"]
    for index in drop_indices:
        args += ["-map", f"-0:{index}"]
    args += ["-c", "copy", str(target)]
    _run(args, timeout=REMUX_TIMEOUT_SECONDS)


def _run(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        # Fixed ffmpeg/ffprobe binary and our own argument list, no shell: safe.
        return subprocess.run(  # noqa: S603
            args, capture_output=True, text=True, check=True, timeout=timeout
        )
    except FileNotFoundError as exc:
        _log_subprocess_failure(args, f"{args[0]} not found; is ffmpeg installed?")
        raise FfmpegError(f"{args[0]} not found; is ffmpeg installed?") from exc
    except subprocess.TimeoutExpired as exc:
        _log_subprocess_failure(args, f"timed out after {timeout:g}s", timeout_seconds=timeout)
        raise FfmpegTimeoutError(f"{args[0]} timed out after {timeout:g}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or f"exit code {exc.returncode}"
        _log_subprocess_failure(args, detail, returncode=exc.returncode)
        raise FfmpegError(detail) from exc


def _log_subprocess_failure(args: list[str], detail: str, **fields: object) -> None:
    """Emit a structured line for a failed ffprobe/ffmpeg call.

    ``command`` names the binary and ``input`` the media file it ran against (the
    argument after ``-i``, when present), so a log search can tie a subprocess
    failure to the offending file even though the per-file warning is logged
    separately by the worker.
    """
    logger.warning(
        "subprocess_failed",
        extra={"command": args[0], "input": _input_path(args), "error": detail, **fields},
    )


def _input_path(args: list[str]) -> str | None:
    """The argument after ``-i`` (the media file), or ``None`` if there is none."""
    for flag, value in itertools.pairwise(args):
        if flag == "-i":
            return value
    return None


class MediaProbe:
    """Per-run cache of the read-only ffprobe inspections, keyed by video path.

    The same video can be referenced by several subtitle files in one scan: the video
    phase probes its subtitle streams, and sync correction probes for an audio stream
    once per matched subtitle. Without caching a video with N matched subtitles would
    pay N audio probes; this memoises each probe so the underlying ffprobe runs at most
    once per video per run.

    A failure is cached as well as a success: a corrupt file that times out or errors
    is probed once and the same outcome is re-raised for every later subtitle, so a bad
    file cannot multiply its cost across a group. The cache lives for one run only (the
    runner creates a fresh instance), so a file that changes between runs is re-probed.
    """

    def __init__(self) -> None:
        self._subtitle_streams: dict[Path, list[SubtitleStream] | FfmpegError] = {}
        self._has_audio: dict[Path, bool | FfmpegError] = {}

    def subtitle_streams(self, video: Path) -> list[SubtitleStream]:
        """Cached :func:`probe_subtitle_streams` for ``video``."""
        if video not in self._subtitle_streams:
            try:
                self._subtitle_streams[video] = probe_subtitle_streams(video)
            except FfmpegError as exc:
                self._subtitle_streams[video] = exc
        cached = self._subtitle_streams[video]
        if isinstance(cached, FfmpegError):
            raise cached
        return cached

    def has_audio_stream(self, video: Path) -> bool:
        """Cached :func:`has_audio_stream` for ``video``."""
        if video not in self._has_audio:
            try:
                self._has_audio[video] = has_audio_stream(video)
            except FfmpegError as exc:
                self._has_audio[video] = exc
        cached = self._has_audio[video]
        if isinstance(cached, FfmpegError):
            raise cached
        return cached
