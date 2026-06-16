"""A tolerant SubRip (SRT) block model used by the cleanup step.

The cleanup rules need to reason about subtitle blocks individually: drop empty or
broken ones, collapse consecutive duplicates, strip ad lines. A full subtitle
library is parsed once into format-specific objects by :mod:`pysubs2` during
conversion, but cleanup works directly on SRT text so it can run on files that were
already SRT without reflowing them through a parser.

The heavy lifting — timestamp parsing and cue serialisation — is delegated to the
``srt`` library, which handles BOM, CRLF, period millisecond separators, and
single-digit hours. What ``srt`` cannot do is preserve malformed input: ``srt.parse``
raises :class:`srt.SRTParseError` on a block with no recognisable timing line, and
``ignore_errors=True`` silently drops such blocks. The cleanup step needs broken
blocks preserved so it can decide their fate rather than have the parser drop them
out from under it. So a thin custom layer remains: the text is split on blank lines
and each chunk is handed to ``srt`` individually; a chunk ``srt`` cannot parse is
kept as a ``broken`` block holding its raw lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

import srt

_BLANK_LINE = re.compile(r"\n[ \t]*\n")


@dataclass
class Block:
    """One subtitle cue: a timing span and its text lines.

    ``start`` and ``end`` are ``None`` for a block with no recognisable timing line (a
    broken block). ``lines`` holds the text lines only; the numeric index is not stored
    because :func:`compose_srt` renumbers from one.
    """

    start: timedelta | None
    end: timedelta | None
    lines: list[str] = field(default_factory=list)

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
        blocks.append(_parse_chunk("\n".join(lines)))
    return blocks


def _parse_chunk(chunk: str) -> Block:
    """Parse one blank-line-delimited chunk, falling back to a broken block.

    ``srt`` parses a chunk that has a recognisable timing line (with or without the
    optional numeric index). Anything it cannot turn into exactly one cue — a chunk
    with no timing line — is kept verbatim as a broken block so cleanup decides whether
    to drop it.
    """
    try:
        cues = list(srt.parse(chunk))
    except srt.SRTParseError:
        cues = []
    if len(cues) == 1:
        cue = cues[0]
        return Block(start=cue.start, end=cue.end, lines=cue.content.split("\n"))
    return Block(start=None, end=None, lines=chunk.split("\n"))


def compose_srt(blocks: list[Block]) -> str:
    """Serialise ``blocks`` back to SRT text, renumbering indices from one."""
    if not blocks:
        return ""
    parts: list[str] = []
    for index, block in enumerate(blocks, start=1):
        if block.is_broken:
            parts.append(f"{index}\n" + "\n".join(block.lines))
        else:
            cue = srt.Subtitle(index, block.start, block.end, "\n".join(block.lines))
            parts.append(srt.compose([cue], reindex=False, strict=False).rstrip("\n"))
    return "\n\n".join(parts) + "\n"
