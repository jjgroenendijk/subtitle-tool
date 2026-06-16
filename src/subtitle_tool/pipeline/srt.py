"""A tolerant SubRip (SRT) block model used by the cleanup step.

The cleanup rules need to reason about subtitle blocks individually: drop empty or
broken ones, collapse consecutive duplicates, strip ad lines. A full subtitle
library is parsed once into format-specific objects by :mod:`pysubs2` during
conversion, but cleanup works directly on SRT text so it can run on files that were
already SRT without reflowing them through a parser.

The heavy lifting — timestamp parsing and cue serialisation — is delegated to the
``srt`` library, which handles BOM, CRLF, period millisecond separators, single-digit
hours, and proprietary positioning suffixes on the timing line. What ``srt`` cannot do
is preserve malformed input: ``srt.parse`` raises :class:`srt.SRTParseError` on a block
with no recognisable timing line, and ``ignore_errors=True`` silently drops such
blocks. The cleanup step needs broken blocks preserved so it can decide their fate
rather than have the parser drop them out from under it. So a thin custom layer
remains: the text is split on blank lines and each chunk is handed to ``srt``; a chunk
``srt`` rejects outright (no timing line) is kept as a ``broken`` block holding its raw
lines.

Two further tolerances bridge the gap to the previous hand-rolled parser. A chunk may
hold more than one cue when a blank separator is missing, so every cue ``srt`` returns
is kept (not just lone ones). And a chunk whose timing line is preceded by stray lines
(a duplicate index, a leftover cue identifier) is retried from the first timing line
onward before being given up as broken. One behaviour intentionally differs: genuinely
off-spec timestamps such as ``00:00:01,5`` are normalised to canonical three-digit
milliseconds (``00:00:01,005``) on output, since normalising subtitles to clean SRT is
the tool's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

import srt

# Used only to find where a cue starts when recovering a chunk that ``srt`` rejected
# because stray lines precede the timing line. Mirrors ``srt``'s own tolerances
# (comma or period millisecond separator, one- or two-digit hours).
_TIMING = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


@dataclass
class Block:
    """One subtitle cue: a timing span and its text lines.

    ``start`` and ``end`` are ``None`` for a block with no recognisable timing line (a
    broken block). ``lines`` holds the text lines only; the numeric index is not stored
    because :func:`compose_srt` renumbers from one. ``proprietary`` carries any SRT
    positioning suffix that followed the end timestamp so it survives a rewrite.
    """

    start: timedelta | None
    end: timedelta | None
    lines: list[str] = field(default_factory=list)
    proprietary: str = ""

    @property
    def is_broken(self) -> bool:
        return self.start is None or self.end is None

    @property
    def is_empty(self) -> bool:
        """A block carrying no visible text (after a valid timing line, or none)."""
        return not any(line.strip() for line in self.lines)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def timing(self) -> str | None:
        """The SRT timing line for this cue, or ``None`` for a broken block."""
        if self.start is None or self.end is None:
            return None
        return (
            f"{srt.timedelta_to_srt_timestamp(self.start)} --> "
            f"{srt.timedelta_to_srt_timestamp(self.end)}"
        )


def parse_srt(text: str) -> list[Block]:
    """Parse SRT ``text`` into blocks, preserving broken ones for the cleanup step."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    blocks: list[Block] = []
    for chunk in _BLANK_LINE.split(normalized):
        lines = chunk.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue
        blocks.extend(_parse_chunk(lines))
    return blocks


def _parse_chunk(lines: list[str]) -> list[Block]:
    """Parse one blank-line-delimited chunk into one or more blocks.

    ``srt`` parses a chunk with a recognisable timing line (with or without the optional
    numeric index) and returns every cue it finds, so a chunk missing a blank separator
    still yields each cue. If ``srt`` rejects the chunk, parsing is retried from the
    first timing line so stray leading lines do not sink an otherwise valid cue. A chunk
    with no timing line at all is kept verbatim as a broken block for cleanup to judge.
    """
    parsed = _parse_with_srt("\n".join(lines))
    if parsed is not None:
        return parsed
    for index, line in enumerate(lines):
        if _TIMING.match(line.strip()):
            parsed = _parse_with_srt("\n".join(lines[index:]))
            if parsed is not None:
                return parsed
            break
    return [Block(start=None, end=None, lines=lines)]


def _parse_with_srt(text: str) -> list[Block] | None:
    """Parse ``text`` with ``srt``; return its cues as blocks, or ``None`` on failure."""
    try:
        cues = list(srt.parse(text))
    except srt.SRTParseError:
        return None
    if not cues:
        return None
    return [
        Block(
            start=cue.start,
            end=cue.end,
            lines=cue.content.split("\n"),
            proprietary=cue.proprietary,
        )
        for cue in cues
    ]


def compose_srt(blocks: list[Block]) -> str:
    """Serialise ``blocks`` back to SRT text, renumbering indices from one."""
    if not blocks:
        return ""
    parts: list[str] = []
    for index, block in enumerate(blocks, start=1):
        if block.is_broken:
            parts.append(f"{index}\n" + "\n".join(block.lines))
        else:
            cue = srt.Subtitle(
                index, block.start, block.end, "\n".join(block.lines), block.proprietary
            )
            parts.append(srt.compose([cue], reindex=False, strict=False).rstrip("\n"))
    return "\n\n".join(parts) + "\n"
