"""Thin wrapper around the ffsubsync CLI for subtitle sync correction.

One operation: align an input SRT to a reference video's audio and write the
shifted result to a new file. It shells out to the bundled ``ffsubsync`` binary so
the work runs in its own process with a hard timeout (a long alignment must never
wedge the worker), parses the offset and alignment score ffsubsync logs, and turns
every failure mode into a typed exception the caller handles. Threshold decisions
(minimum offset, acceptance score, safety cap) live in
:mod:`subtitle_tool.pipeline.steps.sync`; this module only runs the command and
reports what ffsubsync measured.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

FFSUBSYNC = "ffsubsync"

# ffsubsync logs these two lines to stderr on a completed alignment; we read the
# measured shift and its raw cross-correlation score back out of them.
_SCORE_RE = re.compile(r"score:\s*(-?\d+(?:\.\d+)?)")
_OFFSET_RE = re.compile(r"offset seconds:\s*(-?\d+(?:\.\d+)?)")


class SyncError(Exception):
    """ffsubsync could not be run or did not produce a usable alignment."""


class SyncTimeoutError(SyncError):
    """ffsubsync exceeded its per-file time budget and was killed."""


@dataclass(frozen=True)
class SyncResult:
    """The outcome of one completed ffsubsync alignment."""

    offset_seconds: float
    score: float
    output: Path


def synchronize(
    video: Path,
    subtitle_in: Path,
    subtitle_out: Path,
    *,
    max_offset_seconds: float,
    timeout_seconds: float,
) -> SyncResult:
    """Align ``subtitle_in`` to ``video`` writing ``subtitle_out``; report the shift.

    ``max_offset_seconds`` bounds ffsubsync's own search so it never proposes a wildly
    distant alignment; the caller still applies its own cap to the returned offset.
    Raises :class:`SyncTimeoutError` when the time budget is exceeded and :class:`SyncError`
    for any other failure (missing binary, non-zero exit, or output ffsubsync declined
    to write because it could not find an alignment).
    """
    args = [
        _executable(),
        str(video),
        "-i",
        str(subtitle_in),
        "-o",
        str(subtitle_out),
        "--max-offset-seconds",
        # Give ffsubsync headroom past our cap so an over-cap shift is measured and
        # rejected by the caller rather than silently clamped out of the search.
        str(max(max_offset_seconds * 2, max_offset_seconds + 1)),
    ]
    try:
        # Fixed ffsubsync binary and our own argument list, no shell: safe.
        proc = subprocess.run(  # noqa: S603
            args, capture_output=True, text=True, timeout=timeout_seconds
        )
    except FileNotFoundError as exc:
        raise SyncError(f"{FFSUBSYNC} not found; is ffsubsync installed?") from exc
    except subprocess.TimeoutExpired as exc:
        raise SyncTimeoutError(f"ffsubsync timed out after {timeout_seconds:g}s") from exc

    output = proc.stderr or ""
    if proc.returncode != 0:
        detail = (
            output.strip().splitlines()[-1] if output.strip() else (f"exit code {proc.returncode}")
        )
        raise SyncError(detail)

    score = _last_float(_SCORE_RE, output)
    offset = _last_float(_OFFSET_RE, output)
    if score is None or offset is None or not subtitle_out.exists():
        raise SyncError("ffsubsync did not produce an alignment")

    return SyncResult(offset_seconds=offset, score=score, output=subtitle_out)


def _executable() -> str:
    """Locate the ffsubsync console script.

    It is a Python console script installed alongside the interpreter, so it is not
    always on ``PATH`` when the app runs under a dropped user. Prefer ``PATH``, then
    fall back to the interpreter's own bin directory.
    """
    found = shutil.which(FFSUBSYNC)
    if found:
        return found
    candidate = Path(sys.executable).parent / FFSUBSYNC
    if candidate.exists():
        return str(candidate)
    return FFSUBSYNC


def _last_float(pattern: re.Pattern[str], text: str) -> float | None:
    """Return the last value ``pattern`` captured in ``text``, or ``None``.

    ffsubsync may log a value once per framerate ratio it tries; the final line is the
    one for the alignment it settled on.
    """
    matches = pattern.findall(text)
    return float(matches[-1]) if matches else None
