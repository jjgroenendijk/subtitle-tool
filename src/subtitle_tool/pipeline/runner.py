"""The pipeline runner: apply the enabled steps to every subtitle in a scan.

Per video group the runner runs the video phase first (extraction and optional remux);
extracted SRTs join the group's subtitles and flow through the same per-file pipeline.
Per subtitle it loads the bytes once and threads a :class:`WorkItem` through the steps
in dependency order: encoding, conversion, cleanup, sync, detection, naming.

When language filtering is enabled, detection runs before sync so a subtitle the filter
deletes never pays for the expensive alignment; this is safe because sync only shifts
timings, not the dialogue the detector reads. A file marked for deletion skips the rest.

A clean file records no actions and is never written (so rescanning is inert), and a
per-file failure is captured in its :class:`FileResult` without stopping the run. A dry
run shares the exact decision logic and only skips the commit.
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

    ``on_file`` is invoked with each :class:`FileResult` as it finishes, for live
    progress reporting; it never affects processing.

    ``process_paths`` restricts the run to a subset of the inventory (the index passes
    the new and changed files so unchanged ones are skipped); freshly extracted
    subtitles are always processed, and ``None`` processes everything (the CLI).

    ``should_cancel`` is polled at each file boundary (never mid-transform or mid-write,
    so a stop is always safe); once it returns ``True`` the run raises
    :class:`PipelineCancelled` carrying the results gathered so far.
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
    # Detect before sync when filtering, so a deleted file skips alignment (see module
    # docstring for why the reorder is safe).
    filter_first = config.language.filter.enabled
    try:
        normalize_encoding(item, config, raw)
        convert_format(item, config)
        clean(item, config)
        if filter_first:
            detect_language(item, config)
        if not item.delete_file:
            correct_sync(item, config, dry_run=dry_run, probe=probe)
            if not filter_first:
                detect_language(item, config)
            normalize_filename(item, config)
    except Exception as exc:
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
