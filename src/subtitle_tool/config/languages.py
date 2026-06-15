"""Shared catalog of selectable subtitle languages.

The config model validates language codes by shape only (lowercase two-letter
ISO 639-1), which keeps the TOML simple and the loader tolerant. The web UI needs
something friendlier: a fixed list of languages to pick from, labelled with a name
users recognise while still storing the bare code. This module is that catalog —
one mapping of ISO 639-1 code to English language name — plus a helper that turns
it into ``(value, label)`` choices for the form.

The list is curated, not exhaustive: it covers the languages a media library
actually carries. A code outside the catalog is still accepted on load and through
the JSON API (the model only checks the shape), so the catalog constrains the
picker without narrowing what a config file may legitimately contain.
"""

from __future__ import annotations

# ISO 639-1 code -> English name. Kept alphabetical by name for a readable picker.
LANGUAGE_NAMES: dict[str, str] = {
    "af": "Afrikaans",
    "sq": "Albanian",
    "ar": "Arabic",
    "hy": "Armenian",
    "az": "Azerbaijani",
    "eu": "Basque",
    "be": "Belarusian",
    "bn": "Bengali",
    "bs": "Bosnian",
    "bg": "Bulgarian",
    "ca": "Catalan",
    "zh": "Chinese",
    "hr": "Croatian",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "en": "English",
    "et": "Estonian",
    "fi": "Finnish",
    "fr": "French",
    "gl": "Galician",
    "ka": "Georgian",
    "de": "German",
    "el": "Greek",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "is": "Icelandic",
    "id": "Indonesian",
    "ga": "Irish",
    "it": "Italian",
    "ja": "Japanese",
    "kk": "Kazakh",
    "ko": "Korean",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "lb": "Luxembourgish",
    "mk": "Macedonian",
    "ms": "Malay",
    "ml": "Malayalam",
    "mt": "Maltese",
    "mr": "Marathi",
    "nb": "Norwegian Bokmal",
    "no": "Norwegian",
    "nn": "Norwegian Nynorsk",
    "fa": "Persian",
    "pl": "Polish",
    "pt": "Portuguese",
    "pa": "Punjabi",
    "ro": "Romanian",
    "ru": "Russian",
    "sr": "Serbian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "es": "Spanish",
    "sw": "Swahili",
    "sv": "Swedish",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
    "cy": "Welsh",
}


def language_choices() -> list[tuple[str, str]]:
    """Return ``(code, label)`` pairs for the language picker, sorted by name.

    The label combines the language name and its code (e.g. ``"English (en)"``) so
    the meaning is clear while the submitted value stays the Plex-compatible code.
    """
    return [
        (code, f"{name} ({code})")
        for code, name in sorted(LANGUAGE_NAMES.items(), key=lambda item: item[1])
    ]
