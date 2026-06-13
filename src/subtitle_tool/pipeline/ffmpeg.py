"""Thin wrappers around ffprobe and ffmpeg for the video phase.

Three operations: inspect a video's subtitle streams, extract one text stream to an
external SRT, and remux a video dropping a set of streams. Each shells out to the
bundled ffprobe/ffmpeg binaries and turns any failure — a missing binary, a non-zero
exit, unparseable output — into a single :class:`FfmpegError` the caller handles, so
one bad video never crashes a run. Orchestration (collision handling, disk-space and
stability checks, dry-run, atomic replace) lives in :mod:`subtitle_tool.pipeline.video`;
this module only runs commands.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"

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


@dataclass(frozen=True)
class SubtitleStream:
    """One subtitle stream found in a video, as reported by ffprobe."""

    index: int
    codec: str
    language: str | None = None

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
            "stream=index,codec_name:stream_tags=language",
            "-of",
            "json",
            str(video),
        ]
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
        language = (raw.get("tags") or {}).get("language")
        language = language.lower() if language else None
        if language in {"", "und"}:
            language = None
        streams.append(
            SubtitleStream(index=int(index), codec=str(codec).lower(), language=language)
        )
    return streams


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
        ]
    )


def remux_without_streams(video: Path, drop_indices: list[int], target: Path) -> None:
    """Copy ``video`` to ``target`` keeping every stream except ``drop_indices``."""
    args = [FFMPEG, "-nostdin", "-y", "-v", "error", "-i", str(video), "-map", "0"]
    for index in drop_indices:
        args += ["-map", f"-0:{index}"]
    args += ["-c", "copy", str(target)]
    _run(args)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise FfmpegError(f"{args[0]} not found; is ffmpeg installed?") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or f"exit code {exc.returncode}"
        raise FfmpegError(detail) from exc
