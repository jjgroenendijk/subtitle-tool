"""The pipeline runner: apply the enabled steps to every subtitle in a scan.

For each video group the runner first runs the video phase (embedded-subtitle
extraction and optional remux); any SRT files it extracts are appended to the group's
subtitles so they pass through the same per-file pipeline in the same run. The video
phase is inert unless extraction is enabled.

For each subtitle file the runner loads its bytes once, threads a
:class:`~subtitle_tool.pipeline.workitem.WorkItem` through the steps in dependency
order (encoding, then format conversion, then content cleanup, then sync correction
against the matched video, then language detection, then filename normalisation), and
commits the result. A file that needed
no change records no actions and is never written, which keeps rescanning a clean
library inert. A
failure on one file is captured in that file's :class:`FileResult` and never stops
the run.

Dry-run mode runs the exact same decision logic; it simply skips the commit, so the
actions reported as planned are the actions a real run would take.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from subtitle_tool.config.models import Config
from subtitle_tool.pipeline.ffmpeg import MediaProbe
from subtitle_tool.pipeline.models import FileResult, PipelineResult
from subtitle_tool.pipeline.safety import InvalidResult, resolve_collision, safe_write
from subtitle_tool.pipeline.srt import parse_srt
from subtitle_tool.pipeline.steps import (
    clean,
    convert_format,
    correct_sync,
    detect_language,
    normalize_encoding,
    normalize_filename,
)
from subtitle_tool.pipeline.video import process_video
from subtitle_tool.pipeline.workitem import WorkItem
from subtitle_tool.scanner.models import ScanResult


class PipelineCancelled(Exception):
    """Raised when ``should_cancel`` asks the run to stop at a file boundary.

    Carries the per-file results produced before the stop so the caller can record
    the partial progress. Cancellation is only ever observed between files, never
    mid-write, so the atomic-replace layer is never interrupted and no half-written
    file is left behind.
    """

    def __init__(self, results: list[FileResult]) -> None:
        super().__init__("pipeline cancelled")
        self.results = results


def run_pipeline(
    scan_result: ScanResult,
    config: Config,
    *,
    dry_run: bool,
    on_file: Callable[[FileResult], None] | None = None,
    process_paths: set[Path] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> PipelineResult:
    """Process every subtitle in ``scan_result`` and return the per-file outcomes.

    ``on_file`` is invoked with each :class:`FileResult` as soon as that file is
    finished, before the run completes. It lets a caller report live progress (the
    web worker streams these to the browser); it never affects processing and an
    exception it raises is the caller's to handle.

    ``process_paths`` restricts the run to a subset of the inventory: when given, a
    video's extraction phase runs only if the video is in the set, and an inventory
    subtitle is processed only if it is in the set. The media index passes the new and
    changed files here so unchanged files are skipped. Freshly extracted subtitles are
    always processed, since they did not exist when the set was computed. ``None``
    processes everything (the CLI's behaviour).

    ``should_cancel``, when given, is polled at each file boundary; once it returns
    ``True`` the run stops and raises :class:`PipelineCancelled` carrying the results
    gathered so far. The poll sits between files (and before each video phase), never
    during a file's transformation or commit, so a stop is always safe.
    """
    results: list[FileResult] = []
    # One probe cache for the whole run so a video referenced by several subtitles is
    # inspected once: the video phase and every matched subtitle's sync check share it.
    probe = MediaProbe()

    def record(result: FileResult) -> None:
        results.append(result)
        if on_file is not None:
            on_file(result)

    def wanted(path: Path) -> bool:
        return process_paths is None or path in process_paths

    def check_cancelled() -> None:
        if should_cancel is not None and should_cancel():
            raise PipelineCancelled(results)

    for group in scan_result.video_groups:
        # The video phase runs first: embedded text subtitles it extracts join the
        # group's own subtitles and flow through the same per-file pipeline below.
        check_cancelled()
        extracted: list[Path] = []
        if wanted(group.video):
            video_result, extracted = process_video(group.video, config, dry_run, probe)
            if video_result is not None:
                record(video_result)
        for subtitle in group.subtitles:
            if wanted(subtitle):
                check_cancelled()
                record(_process(subtitle, config, dry_run, group.video, probe))
        for subtitle in extracted:
            check_cancelled()
            record(_process(subtitle, config, dry_run, group.video, probe))
    for standalone in scan_result.standalone_subtitles:
        if wanted(standalone.subtitle):
            check_cancelled()
            result = _process(standalone.subtitle, config, dry_run, None, probe)
            # The scanner's match warnings (ambiguous/unmatched) are otherwise lost:
            # an otherwise-clean standalone subtitle records no pipeline warning, so
            # carry the scanner's reasons onto its result for the report surfaces.
            if standalone.warnings:
                result = replace(
                    result,
                    warnings=[w.message for w in standalone.warnings] + result.warnings,
                )
            record(result)
    return PipelineResult(file_results=results, dry_run=dry_run)


def _process(
    path: Path, config: Config, dry_run: bool, video: Path | None, probe: MediaProbe
) -> FileResult:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return FileResult(source=path, target=path, error=f"could not read file: {exc}")

    video_stem = video.stem if video is not None else None
    item = WorkItem(source=path, target=path, text="", video_stem=video_stem, video=video)
    try:
        normalize_encoding(item, config, raw)
        convert_format(item, config)
        clean(item, config)
        correct_sync(item, config, dry_run=dry_run, probe=probe)
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

    applied = False
    if item.actions and not dry_run:
        applied = _commit(item)

    return FileResult(
        source=item.source,
        target=item.target,
        actions=item.actions,
        warnings=item.warnings,
        applied=applied,
    )


def _commit(item: WorkItem) -> bool:
    """Write the transformed content and remove the source when required.

    Returns whether a change actually reached disk. A result the safety validator
    rejects, or a write that fails, leaves the original untouched and returns
    ``False``, so the run reports the file as skipped rather than changed.
    """
    if item.delete_file:
        # Language filtering decided the file is unwanted: remove it instead of
        # writing a result. No converted target was written (writes happen only here).
        try:
            item.source.unlink(missing_ok=True)
        except OSError as exc:
            item.warn(f"could not delete unwanted-language subtitle: {exc}")
            return False
        return True

    final = item.target
    if final != item.source and final.exists():
        final = resolve_collision(final)
        item.warn(f"target {item.target.name} already exists; wrote {final.name} instead")
        item.target = final

    encoding = item.output_encoding
    try:
        safe_write(
            final,
            item.text,
            validate=lambda path: _validate_result(path, encoding),
            encoding=encoding,
        )
    except InvalidResult as exc:
        item.warn(f"result failed validation, left original untouched: {exc}")
        return False
    except (OSError, UnicodeError) as exc:
        item.warn(f"could not write result, left original untouched: {exc}")
        return False

    if item.remove_source and item.source != final:
        try:
            item.source.unlink(missing_ok=True)
        except OSError as exc:
            item.warn(f"wrote {final.name} but could not remove {item.source.name}: {exc}")

    # The result reached disk even if the redundant source could not be removed.
    return True


def _validate_result(path: Path, encoding: str = "utf-8") -> None:
    """Reject an empty result, or an SRT result that has no parseable cues."""
    text = path.read_text(encoding=encoding)
    if not text.strip():
        raise InvalidResult("result is empty")
    if path.suffix.lower() == ".srt" and not any(block.timing for block in parse_srt(text)):
        raise InvalidResult("result has no subtitle cues")
