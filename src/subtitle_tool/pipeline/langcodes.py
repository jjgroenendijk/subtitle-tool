"""ISO 639-2 to ISO 639-1 language-code resolution.

ffprobe reports a stream's language as an ISO 639-2 three-letter code (and may use
either the bibliographic ``B`` or terminologic ``T`` variant, which differ for a
handful of languages such as ``ger``/``deu`` or ``fre``/``fra``). The rest of the
tool — config language lists, subtitle filenames Plex reads — speaks ISO 639-1
two-letter codes. This module bridges the two through the ``iso639-lang`` library
rather than a hand-maintained table, so every registered language resolves, not just
the handful a curated table happened to list.

An unknown code, or a language with no ISO 639-1 equivalent, maps to ``None``: the
extracted subtitle then carries no language token in its name and the detection step
fills one in from the content, so a missing mapping degrades gracefully rather than
guessing.
"""

from __future__ import annotations

from iso639 import Lang
from iso639.exceptions import DeprecatedLanguageValue, InvalidLanguageValue


def iso639_2_to_1(code: str | None) -> str | None:
    """Return the ISO 639-1 two-letter code for a 639-2 ``code``, or ``None``.

    The lookup is case-insensitive and accepts both the bibliographic and
    terminologic 639-2 variants. ``None``, an empty string, the explicit
    "undetermined" code (``und``), unknown codes, and codes for languages that have
    no ISO 639-1 form all return ``None``.
    """
    if not code:
        return None
    try:
        lang = Lang(code.strip().lower())
    except (InvalidLanguageValue, DeprecatedLanguageValue):
        return None
    # Languages without an ISO 639-1 form (including "und") expose an empty ``pt1``.
    return lang.pt1 or None
