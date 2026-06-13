"""The pipeline runner: apply the enabled steps to every subtitle in a scan.

For each subtitle file the runner loads its bytes once, threads a
:class:`~subtitle_tool.pipeline.workitem.WorkItem` through the steps in dependency
order (encoding, then format conversion, then content cleanup, then language
detection, then filename normalisation), and commits the result. A file that needed
no change records no actions and is never written, which keeps rescanning a clean
library inert. A
failure on one file is captured in that file's :class:`FileResult` and never stops
the run.

Dry-run mode runs the exact same decision logic; it simply skips the commit, so the
actions reported as planned are the actions a real run would take.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.models import FileResult, PipelineResult
from subtitle_tool.pipeline.safety import InvalidResult, resolve_collision, safe_write
from subtitle_tool.pipeline.srt import parse_srt
from subtitle_tool.pipeline.steps import (
    clean,
    convert_format,
    detect_language,
    normalize_encoding,
    normalize_filename,
)
from subtitle_tool.pipeline.workitem import WorkItem
from subtitle_tool.scanner.models import ScanResult


def run_pipeline(
    scan_result: ScanResult,
    config: Config,
    *,
    dry_run: bool,
    on_file: Callable[[FileResult], None] | None = None,
) -> PipelineResult:
    """Process every subtitle in ``scan_result`` and return the per-file outcomes.

    ``on_file`` is invoked with each :class:`FileResult` as soon as that file is
    finished, before the run completes. It lets a caller report live progress (the
    web worker streams these to the browser); it never affects processing and an
    exception it raises is the caller's to handle.
    """
    results: list[FileResult] = []

    def record(result: FileResult) -> None:
        results.append(result)
        if on_file is not None:
            on_file(result)

    for group in scan_result.video_groups:
        for subtitle in group.subtitles:
            record(_process(subtitle, config, dry_run, group.video.stem))
    for standalone in scan_result.standalone_subtitles:
        record(_process(standalone.subtitle, config, dry_run, None))
    return PipelineResult(file_results=results, dry_run=dry_run)


def _process(path: Path, config: Config, dry_run: bool, video_stem: str | None) -> FileResult:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return FileResult(source=path, target=path, error=f"could not read file: {exc}")

    item = WorkItem(source=path, target=path, text="", video_stem=video_stem)
    try:
        normalize_encoding(item, config, raw)
        convert_format(item, config)
        clean(item, config)
        detect_language(item, config)
        normalize_filename(item, config)
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
        return FileResult(
            source=item.source,
            target=item.target,
            actions=item.actions,
            warnings=item.warnings,
            error=f"processing failed: {exc}",
        )

    if item.actions and not dry_run:
        _commit(item)

    return FileResult(
        source=item.source,
        target=item.target,
        actions=item.actions,
        warnings=item.warnings,
    )


def _commit(item: WorkItem) -> None:
    """Write the transformed content and remove the source when required."""
    if item.delete_file:
        # Language filtering decided the file is unwanted: remove it instead of
        # writing a result. No converted target was written (writes happen only here).
        try:
            item.source.unlink(missing_ok=True)
        except OSError as exc:
            item.warn(f"could not delete unwanted-language subtitle: {exc}")
        return

    final = item.target
    if final != item.source and final.exists():
        final = resolve_collision(final)
        item.warn(f"target {item.target.name} already exists; wrote {final.name} instead")
        item.target = final

    try:
        safe_write(final, item.text, validate=_validate_result)
    except InvalidResult as exc:
        item.warn(f"result failed validation, left original untouched: {exc}")
        return
    except OSError as exc:
        item.warn(f"could not write result, left original untouched: {exc}")
        return

    if item.remove_source and item.source != final:
        try:
            item.source.unlink(missing_ok=True)
        except OSError as exc:
            item.warn(f"wrote {final.name} but could not remove {item.source.name}: {exc}")


def _validate_result(path: Path) -> None:
    """Reject an empty result, or an SRT result that has no parseable cues."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise InvalidResult("result is empty")
    if path.suffix.lower() == ".srt" and not any(block.timing for block in parse_srt(text)):
        raise InvalidResult("result has no subtitle cues")
