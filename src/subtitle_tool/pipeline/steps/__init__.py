"""The individual pipeline steps, applied in dependency order by the runner."""

from subtitle_tool.pipeline.steps.cleanup import clean
from subtitle_tool.pipeline.steps.conversion import convert_format
from subtitle_tool.pipeline.steps.encoding import normalize_encoding
from subtitle_tool.pipeline.steps.naming import normalize_filename

__all__ = [
    "clean",
    "convert_format",
    "normalize_encoding",
    "normalize_filename",
]
