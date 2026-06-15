"""Worker progress-reporting tests, focused on the advertised work total."""

from __future__ import annotations

from pathlib import Path

from subtitle_tool.config.models import Config
from tests.jobs.test_worker import build_library, make_worker, wait_until_idle


def test_extraction_work_never_reports_processed_above_total(tmp_path: Path, monkeypatch) -> None:
    # The video phase emits a video result plus subtitles it extracted, none of which
    # are in the pre-run inventory the total is seeded from. Progress must raise the
    # advertised total to cover them rather than report processed past a fixed total.
    media = tmp_path / "media"
    build_library(media)  # two inventory subtitles, so the seeded total is 2
    config = Config.model_validate({"scan": {"media_paths": [str(media)]}})
    worker, store, broker = make_worker(tmp_path, config)

    import subtitle_tool.jobs.worker as worker_module
    from subtitle_tool.pipeline import FileResult
    from subtitle_tool.pipeline.models import Action, ActionType

    def fake_run_pipeline(scan_result, cfg, *, dry_run, on_file=None, **_kwargs):
        video = media / "Movie (2020).mkv"
        # One video-phase result, the two inventory subtitles, and two freshly
        # extracted subtitles: five processed files against a seeded total of two.
        emitted = [
            FileResult(
                source=video,
                target=video,
                actions=[Action(ActionType.EXTRACT_SUBTITLE, "extract stream 2 (eng)")],
            ),
            FileResult(source=media / "Movie (2020).fr.ass", target=media / "Movie (2020).fr.srt"),
            FileResult(source=media / "Movie (2020).en.srt", target=media / "Movie (2020).en.srt"),
            FileResult(source=media / "Movie (2020).en.srt", target=media / "Movie (2020).en.srt"),
            FileResult(source=media / "Movie (2020).de.srt", target=media / "Movie (2020).de.srt"),
        ]
        for result in emitted:
            if on_file is not None:
                on_file(result)

    monkeypatch.setattr(worker_module, "run_pipeline", fake_run_pipeline)

    job_id = worker.start(dry_run=True)
    assert job_id is not None
    wait_until_idle(worker)

    progress = [event for event in broker.events if event["event"] == "file_processed"]
    # No progress event ever advertises fewer total files than have been processed.
    assert all(event["processed"] <= event["total"] for event in progress)
    # The final total grew to cover every processed file, not the seeded inventory of 2.
    assert progress[-1]["processed"] == 5
    assert progress[-1]["total"] == 5
    finished = broker.events[-1]
    assert finished["event"] == "job_finished"
    assert finished["total"] == 5
    job = store.get_job(job_id)
    assert job is not None
    assert job.total_files == 5
