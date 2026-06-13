"""The subtitle pipeline: per-file transformations behind a safe atomic write.

The runner applies the enabled steps to each subtitle found by a scan, in
dependency order, recording the actions taken and warnings raised per file and
continuing past per-file failures. Every rewrite goes through the temp-file plus
atomic-replace safety layer, and a dry run reports planned actions without writing.
"""

from subtitle_tool.pipeline.models import (
    Action,
    ActionType,
    FileResult,
    PipelineResult,
)
from subtitle_tool.pipeline.runner import run_pipeline

__all__ = [
    "Action",
    "ActionType",
    "FileResult",
    "PipelineResult",
    "run_pipeline",
]
