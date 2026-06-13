"""Library scanning: directory walking, classification, and subtitle matching."""

from subtitle_tool.scanner.models import (
    MatchWarning,
    ScanResult,
    StandaloneSubtitle,
    VideoGroup,
    WarningReason,
)
from subtitle_tool.scanner.scanner import scan, scan_paths
from subtitle_tool.scanner.walk import (
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    is_subtitle,
    is_video,
    iter_files,
)

__all__ = [
    "SUBTITLE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "MatchWarning",
    "ScanResult",
    "StandaloneSubtitle",
    "VideoGroup",
    "WarningReason",
    "is_subtitle",
    "is_video",
    "iter_files",
    "scan",
    "scan_paths",
]
