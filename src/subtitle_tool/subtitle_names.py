"""Shared subtitle filename domain logic.

External subtitles follow the Plex convention ``<video basename>[.lang][.flags].ext``
(for example ``Movie (2020).en.sdh.srt``). Parsing that name into its video basename,
language code, and flag tokens is shared domain knowledge: the scanner uses it to find
the video a subtitle belongs to, the index records the parsed language and flags, and
the pipeline's detection and naming steps read the language token already on disk.

It lives in this neutral module rather than under any one feature package so that none
of those callers implies ownership of the parsing. Keep filename-shape knowledge here;
matching rules stay in ``scanner.matching``, index persistence in ``index.store``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Recognised trailing tokens on a subtitle filename. Flags describe the subtitle
# variant; a language token is a two- or three-letter code. Both are peeled off the
# name to recover the video basename the subtitle belongs to.
_FLAG_TOKENS = frozenset({"forced", "sdh", "hi", "cc", "foreign", "default"})
_LANGUAGE_TOKEN = re.compile(r"^[a-z]{2,3}$")


def split_subtitle_name(path: Path) -> tuple[str, str | None, list[str]]:
    """Split a subtitle filename into its video basename, language, and flags.

    Peels recognised flag tokens (right to left) and then a single language token off
    the stem. The remaining left-hand portion is the video basename the subtitle is
    expected to share. A token is only peeled while something is left to its left, so
    a bare ``en.srt`` keeps ``en`` as its basename rather than emptying it.
    """
    parts = path.name[: -len(path.suffix)].split(".") if path.suffix else path.name.split(".")
    flags: list[str] = []
    while len(parts) > 1 and parts[-1].lower() in _FLAG_TOKENS:
        flags.insert(0, parts.pop().lower())
    language: str | None = None
    if len(parts) > 1 and _LANGUAGE_TOKEN.match(parts[-1].lower()):
        language = parts.pop().lower()
    return ".".join(parts), language, flags
