"""Encoding step: detect the character encoding and normalise to UTF-8.

This runs first: every later step works on decoded text, so the file's bytes have
to become a Python string before anything else happens. ``charset-normalizer``
identifies the most likely encoding; the bytes are decoded with it and the decoded
text replaces the work item's content. An action is recorded only when the source
was not already UTF-8 (or pure ASCII, a UTF-8 subset) and conversion is enabled, so
a file that is already UTF-8 produces no change and triggers no write.

When UTF-8 conversion is disabled the file's original encoding is remembered on the
work item so the commit re-encodes the result with it. Without this a later cleanup
or rename action would still be written as UTF-8 by the default-UTF-8 commit path,
silently transcoding a file the user asked to leave in its original encoding.
"""

from __future__ import annotations

from charset_normalizer import from_bytes

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.models import ActionType
from subtitle_tool.pipeline.workitem import WorkItem

# Encodings that already are UTF-8 (or a strict subset of it); decoding leaves the
# bytes unchanged, so no conversion is needed.
_UTF8_ALIASES = frozenset({"utf_8", "utf-8", "ascii"})


def normalize_encoding(item: WorkItem, config: Config, raw: bytes) -> None:
    """Decode ``raw`` into ``item.text``, recording a conversion when one happened."""
    match = from_bytes(raw).best()
    if match is None:
        # Nothing decoded cleanly (typically an empty file); fall back to a lossless
        # latin-1 decode so later steps still have text to work with.
        item.text = raw.decode("latin-1")
        encoding = "latin-1"
    else:
        item.text = str(match)
        encoding = (match.encoding or "").lower()

    if not config.format.convert_to_utf8:
        # Preserve the original encoding for the commit so a later step's write does
        # not transcode the file the user asked to leave alone. UTF-8 (and its ASCII
        # subset) round-trips losslessly, so leaving the default is correct there too.
        if encoding not in _UTF8_ALIASES:
            item.output_encoding = encoding
        return
    if encoding in _UTF8_ALIASES:
        return
    item.record(
        ActionType.CONVERT_ENCODING,
        f"convert encoding from {encoding} to utf-8",
    )
