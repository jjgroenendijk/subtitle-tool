"""A tolerant SubRip (SRT) block model used by the cleanup step.

The cleanup rules need to reason about subtitle blocks individually: drop empty or
broken ones, collapse consecutive duplicates, strip ad lines. A full subtitle
library is parsed once into format-specific objects by :mod:`pysubs2` during
conversion, but cleanup works directly on SRT text so it can run on files that were
already SRT without reflowing them through a parser.

The parser is deliberately forgiving. It splits on blank lines, locates the timing
line within each block (ignoring the optional numeric index), and keeps everything
else as text. A block with no recognisable timing line is preserved as ``broken``
so the cleanup step decides its fate rather than the parser silently dropping it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Accept both the SRT comma and the occasional period as the millisecond separator,
# and one- or two-digit hours, so slightly off-spec files still parse.
_TIMING = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


@dataclass
class Block:
    """One subtitle cue: a timing line and its text lines.

    ``timing`` is ``None`` for a block with no recognisable timing line (a broken
    block). ``lines`` holds the text lines only; the numeric index is not stored
    because :func:`compose_srt` renumbers from one.
    """

    timing: str | None
    lines: list[str] = field(default_factory=list)

    @property
    def is_broken(self) -> bool:
        return self.timing is None

    @property
    def is_empty(self) -> bool:
        """A block carrying no visible text (after a valid timing line, or none)."""
        return not any(line.strip() for line in self.lines)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def parse_srt(text: str) -> list[Block]:
    """Parse SRT ``text`` into blocks, preserving broken ones for the cleanup step."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    blocks: list[Block] = []
    for chunk in _BLANK_LINE.split(normalized):
        lines = [line for line in chunk.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue
        timing_index = next(
            (i for i, line in enumerate(lines) if _TIMING.match(line.strip())), None
        )
        if timing_index is None:
            blocks.append(Block(timing=None, lines=lines))
        else:
            blocks.append(
                Block(timing=lines[timing_index].strip(), lines=lines[timing_index + 1 :])
            )
    return blocks


def compose_srt(blocks: list[Block]) -> str:
    """Serialise ``blocks`` back to SRT text, renumbering indices from one."""
    parts: list[str] = []
    for index, block in enumerate(blocks, start=1):
        if block.timing is None:
            body = "\n".join(block.lines)
        elif block.lines:
            body = block.timing + "\n" + "\n".join(block.lines)
        else:
            body = block.timing
        parts.append(f"{index}\n{body}")
    return "\n\n".join(parts) + "\n" if parts else ""
