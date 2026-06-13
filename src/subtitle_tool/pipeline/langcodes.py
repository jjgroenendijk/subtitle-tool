"""ISO 639-2 to ISO 639-1 language-code mapping.

ffprobe reports a stream's language as an ISO 639-2 three-letter code (and may use
either the bibliographic ``B`` or terminologic ``T`` variant, which differ for a
handful of languages). The rest of the tool — config language lists, subtitle
filenames Plex reads — speaks ISO 639-1 two-letter codes. This module bridges the
two with a small table covering the languages a media library actually contains.

An unknown code maps to ``None``: the extracted subtitle then carries no language
token in its name and the detection step fills one in from the content, so a missing
entry degrades gracefully rather than guessing.
"""

from __future__ import annotations

# Both bibliographic and terminologic 639-2 codes map to the same 639-1 code, so a
# tag of "ger" or "deu" both resolve to "de". Only the differing variants need both
# spellings listed.
_ISO_639_2_TO_1: dict[str, str] = {
    "ara": "ar",
    "bul": "bg",
    "ces": "cs",
    "cze": "cs",
    "dan": "da",
    "deu": "de",
    "ger": "de",
    "ell": "el",
    "gre": "el",
    "eng": "en",
    "spa": "es",
    "est": "et",
    "fin": "fi",
    "fra": "fr",
    "fre": "fr",
    "heb": "he",
    "hin": "hi",
    "hrv": "hr",
    "hun": "hu",
    "ind": "id",
    "isl": "is",
    "ice": "is",
    "ita": "it",
    "jpn": "ja",
    "kor": "ko",
    "lit": "lt",
    "lav": "lv",
    "nld": "nl",
    "dut": "nl",
    "nor": "no",
    "nob": "nb",
    "pol": "pl",
    "por": "pt",
    "ron": "ro",
    "rum": "ro",
    "rus": "ru",
    "slk": "sk",
    "slo": "sk",
    "slv": "sl",
    "srp": "sr",
    "swe": "sv",
    "tha": "th",
    "tur": "tr",
    "ukr": "uk",
    "vie": "vi",
    "zho": "zh",
    "chi": "zh",
}


def iso639_2_to_1(code: str | None) -> str | None:
    """Return the ISO 639-1 two-letter code for a 639-2 ``code``, or ``None``.

    The lookup is case-insensitive. ``None``, an empty string, and the explicit
    "undetermined" code (``und``) all return ``None``.
    """
    if not code:
        return None
    return _ISO_639_2_TO_1.get(code.strip().lower())
