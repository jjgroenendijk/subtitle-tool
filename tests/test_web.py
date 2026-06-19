"""Tests for the web app: pages, JSON API, config round-trip, and background scans."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from subtitle_tool import __version__
from subtitle_tool.config import BootstrapSettings, load_config, save_config
from subtitle_tool.config.models import Config
from subtitle_tool.jobs.models import JobStatus
from subtitle_tool.web import create_app
from tests.helpers import block_worker_scan, build_library, media_config, wait_idle

if TYPE_CHECKING:
    from pathlib import Path


def configure_media(config_dir: Path, media: Path) -> None:
    save_config(media_config(media), config_dir / "config.toml")


def test_legacy_health_endpoint_reports_ok(client: TestClient) -> None:
    # Kept as a deprecated alias so existing container health checks keep working.
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_liveness_reports_alive(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "version": __version__}


def test_readiness_reports_ready_when_dependencies_are_usable(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {"config_dir", "job_store", "index_store"} <= set(body["checks"])
    assert all(check["ok"] for check in body["checks"].values())


def test_readiness_reports_503_when_a_store_is_unusable(client: TestClient) -> None:
    # A closed SQLite connection stands in for an unusable local-state dependency:
    # readiness must fail (503) and name the failing check, not merely report alive.
    client.app.state.store.close()

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["job_store"]["ok"] is False


def test_dashboard_renders(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "Scan now" in response.text


def test_dashboard_jobs_table_lives_in_a_scroll_wrapper(client: TestClient) -> None:
    # The recent-jobs table is wide (eleven columns), so it sits in the shared
    # .table-wrap panel that scrolls horizontally instead of forcing the whole page
    # sideways on narrow layouts (see docs/design-requirements.md table treatment).
    response = client.get("/")

    assert '<div class="table-wrap">' in response.text
    wrapper, _, after = response.text.partition('<div class="table-wrap">')
    assert '<table id="jobs">' in after
    assert '<table id="jobs">' not in wrapper


def test_sidebar_marks_the_current_route(client: TestClient) -> None:
    # The active link carries an accessible current-page marker on each page.
    dashboard = client.get("/")
    assert '<a href="/" class="active" aria-current="page">Dashboard</a>' in dashboard.text

    config = client.get("/config")
    assert '<a href="/config" class="active" aria-current="page">Configuration</a>' in config.text
    # Only the current route is marked, not every link.
    assert config.text.count('aria-current="page"') == 1


def test_config_page_lists_every_section(client: TestClient) -> None:
    response = client.get("/config")

    assert response.status_code == 200
    for section in ("scan", "watcher", "extraction", "format", "language", "cleanup", "history"):
        assert section in response.text
    # Nested fields are present too.
    assert "language.filter.enabled" in response.text


def test_config_page_renders_language_pickers(client: TestClient) -> None:
    response = client.get("/config")

    assert response.status_code == 200
    # A filterable Alpine checkbox list (x-data), not a multi-select or textarea.
    assert 'class="lang-picker" data-field="extraction.languages" x-data="langPicker"' in (
        response.text
    )
    assert 'type="checkbox" name="extraction.languages" value="en"' in response.text
    assert 'data-field="language.filter.wanted_languages"' in response.text
    assert "English (en)" in response.text
    assert 'class="lang-count muted" x-text="countLabel"' in response.text


def test_config_page_renders_a_media_path_picker(client: TestClient) -> None:
    response = client.get("/config")

    assert response.status_code == 200
    # An Alpine directory-picker component over /api/browse (x-for selected list).
    assert 'class="dir-picker" data-target="scan.media_paths" x-data="dirPicker"' in response.text
    assert 'x-for="(path, index) in selected"' in response.text
    assert 'x-on:click="toggleBrowser"' in response.text


def test_dir_picker_textarea_seeds_existing_media_paths(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    media.mkdir(parents=True)
    configure_media(config_dir, media)

    response = client.get("/config")

    assert response.status_code == 200
    # The textarea must keep the server-rendered paths so dirPicker.init() seeds
    # Alpine from them; an empty textarea would persist [] and disable scans.
    assert f'x-model="text">{media}</textarea>' in response.text


def test_base_template_loads_vendored_alpine(client: TestClient) -> None:
    response = client.get("/config")

    assert response.status_code == 200
    # Served from a pinned local asset, never a CDN; loaded after app.js so the
    # alpine:init component registration runs before Alpine starts.
    app_index = response.text.index('src="/static/app.js"')
    alpine_index = response.text.index('src="/static/vendor/alpine.csp.min.js"')
    assert app_index < alpine_index
    assert "cdn.jsdelivr" not in response.text
    assert "unpkg" not in response.text


def test_vendored_alpine_asset_is_served(client: TestClient) -> None:
    response = client.get("/static/vendor/alpine.csp.min.js")

    assert response.status_code == 200
    # window.Alpine confirms Alpine; "prohibited" (its x-html ban) marks the CSP
    # build, distinguishing it from the standard build.
    assert "window.Alpine" in response.text
    assert "prohibited" in response.text


def test_config_page_warns_about_missing_media_paths(client: TestClient, config_dir: Path) -> None:
    save_config(
        Config.model_validate({"scan": {"media_paths": ["/does/not/exist"]}}),
        config_dir / "config.toml",
    )

    response = client.get("/config")

    assert response.status_code == 200
    assert "not directories visible inside the" in response.text
    assert "/does/not/exist" in response.text


def test_browse_lists_subdirectories_within_root(tmp_path: Path) -> None:
    root = tmp_path / "media"
    (root / "movies").mkdir(parents=True)
    (root / "tv").mkdir()
    (root / "notes.txt").write_text("x", encoding="utf-8")
    app = create_app(BootstrapSettings(CONFIG_DIR=tmp_path / "config", BROWSE_ROOT=root))

    with TestClient(app) as browse_client:
        # No path defaults to the configured root; files are excluded, dirs sorted.
        body = browse_client.get("/api/browse").json()
        assert body["path"] == str(root)
        assert body["parent"] is None  # at the root, no escaping upward
        assert [entry["name"] for entry in body["entries"]] == ["movies", "tv"]

        # Navigating into a child reports a parent back to the root.
        child = browse_client.get("/api/browse", params={"path": str(root / "movies")}).json()
        assert child["parent"] == str(root)


def test_browse_rejects_paths_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    app = create_app(BootstrapSettings(CONFIG_DIR=tmp_path / "config", BROWSE_ROOT=root))

    with TestClient(app) as browse_client:
        outside = browse_client.get("/api/browse", params={"path": str(tmp_path)})
        assert outside.status_code == 400
        assert "outside" in outside.json()["error"]

        missing = browse_client.get("/api/browse", params={"path": str(root / "nope")})
        assert missing.status_code == 404


def test_config_form_saves_selected_languages(client: TestClient, config_dir: Path) -> None:
    response = client.post(
        "/config",
        data={
            "language.filter.enabled": "on",
            "language.filter.wanted_languages": ["en", "nl"],
            "language.filter.action": "warn",
            "extraction.languages": ["fr"],
        },
    )

    assert response.status_code == 200
    saved = load_config(config_dir / "config.toml")
    assert saved.language.filter.wanted_languages == ["en", "nl"]
    assert saved.extraction.languages == ["fr"]


def test_api_config_round_trips(client: TestClient, config_dir: Path) -> None:
    payload = Config.model_validate(
        {
            "scan": {"media_paths": ["/media/movies"], "interval_hours": 12},
            "language": {"filter": {"enabled": True, "wanted_languages": ["en", "nl"]}},
        }
    ).model_dump(mode="json")

    put = client.put("/api/config", json=payload)
    assert put.status_code == 200

    got = client.get("/api/config").json()
    assert got["scan"]["media_paths"] == ["/media/movies"]
    assert got["language"]["filter"]["wanted_languages"] == ["en", "nl"]
    # The file on disk validates back to the same config.
    assert load_config(config_dir / "config.toml").scan.interval_hours == 12


def test_api_config_rejects_invalid(client: TestClient, config_dir: Path) -> None:
    response = client.put("/api/config", json={"scan": {"interval_hours": 0}})

    assert response.status_code == 422
    assert "errors" in response.json()
    assert not (config_dir / "config.toml").exists()


def test_config_form_saves_and_redisplays(client: TestClient, config_dir: Path) -> None:
    response = client.post(
        "/config",
        data={
            "scan.media_paths": "/media/movies\n/media/tv",
            "scan.interval_hours": "8",
            "format.convert_to_utf8": "on",  # a ticked checkbox
            "history.retention_limit": "100",
            "language.min_confidence": "0.8",
            "language.filter.action": "warn",
            "watcher.stability_window_seconds": "30",
        },
    )

    assert response.status_code == 200
    assert "Configuration saved" in response.text
    saved = load_config(config_dir / "config.toml")
    assert saved.scan.media_paths == ["/media/movies", "/media/tv"]
    assert saved.scan.interval_hours == 8
    # An unticked checkbox (absent from the form) becomes False.
    assert saved.format.convert_to_srt is False
    assert saved.format.convert_to_utf8 is True


def test_config_form_reports_validation_errors(client: TestClient, config_dir: Path) -> None:
    response = client.post("/config", data={"scan.interval_hours": "0"})

    assert response.status_code == 422
    assert "was not saved" in response.text
    assert not (config_dir / "config.toml").exists()


def test_create_job_runs_in_background_and_is_recorded(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    created = client.post("/api/jobs", json={"mode": "dry-run"})
    assert created.status_code == 201
    job_id = created.json()["id"]
    # The request returned immediately; the UI stays responsive while it runs.
    assert client.get("/").status_code == 200

    wait_idle(client)

    history = client.get("/api/jobs").json()
    assert any(job["id"] == job_id for job in history)
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "succeeded"
    assert detail["total_files"] == 1
    assert detail["changed_files"] == 1
    # Coverage counters are serialized so clients can distinguish discovered
    # inventory from processed work.
    assert detail["videos_found"] == 1
    assert detail["subtitles_found"] == 1
    assert detail["processed_files"] == 1
    assert detail["unwanted_subtitles"] == 0
    assert detail["files"][0]["changed"]


def test_reset_index_clears_the_library(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)
    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)
    assert "Movie (2020).mkv" in client.get("/library").text

    reset = client.post("/config/reset-index", follow_redirects=False)
    assert reset.status_code == 303
    assert reset.headers["location"] == "/config?index_reset=1"

    # The index is empty and the config page confirms the action.
    assert "No indexed videos yet" in client.get("/library").text
    assert "Media index cleared" in client.get("/config?index_reset=1").text


def test_config_page_offers_an_index_reset_action(client: TestClient) -> None:
    response = client.get("/config")
    assert response.status_code == 200
    assert 'action="/config/reset-index"' in response.text
    # Guarded by a confirmation prompt before the destructive POST.
    assert "data-confirm=" in response.text


def test_scan_button_redirects_to_job(client: TestClient, config_dir: Path, tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    response = client.post("/scan", data={"mode": "dry-run"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs/")
    wait_idle(client)


def test_scan_button_rejected_while_busy_redirects_with_notice(
    client: TestClient, config_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    entered, gate = block_worker_scan(monkeypatch)

    created = client.post("/api/jobs", json={"mode": "real"})
    job_id = created.json()["id"]
    entered.wait()

    rejected = client.post("/scan", data={"mode": "dry-run"}, follow_redirects=False)
    assert rejected.status_code == 303
    assert rejected.headers["location"] == "/?busy=1"

    page = client.get("/?busy=1")
    assert "your request was not started" in page.text
    # The notice links to the job that is actually running.
    assert f'href="/jobs/{job_id}"' in page.text

    gate.open()
    wait_idle(client)

    # With no rejection flag the notice is absent.
    assert "your request was not started" not in client.get("/").text


def test_stop_routes_redirect(client: TestClient) -> None:
    # No job is running, so a stop is a safe no-op that still redirects back.
    dashboard_stop = client.post("/scan/stop", follow_redirects=False)
    assert dashboard_stop.status_code == 303
    assert dashboard_stop.headers["location"] == "/"

    job_stop = client.post("/jobs/1/stop", follow_redirects=False)
    assert job_stop.status_code == 303
    assert job_stop.headers["location"] == "/jobs/1"


def test_clear_jobs_empties_history(client: TestClient, config_dir: Path, tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    client.post("/api/jobs", json={"mode": "dry-run"})
    wait_idle(client)
    assert client.get("/api/jobs").json()

    cleared = client.post("/jobs/clear", follow_redirects=False)
    assert cleared.status_code == 303
    assert cleared.headers["location"] == "/"
    assert client.get("/api/jobs").json() == []


def test_cancel_api_409_when_no_job_running(client: TestClient) -> None:
    assert client.post("/api/jobs/999/cancel").status_code == 409


def test_cancel_api_stops_running_job(
    client: TestClient, config_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    entered, gate = block_worker_scan(monkeypatch)

    created = client.post("/api/jobs", json={"mode": "real"})
    job_id = created.json()["id"]
    entered.wait()

    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelling"

    gate.open()
    wait_idle(client)

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "cancelled"
    assert detail["finished_at"] is not None


def test_running_job_page_shows_stop_button(
    client: TestClient, config_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    entered, gate = block_worker_scan(monkeypatch)

    created = client.post("/api/jobs", json={"mode": "real"})
    job_id = created.json()["id"]
    entered.wait()

    page = client.get(f"/jobs/{job_id}")
    assert page.status_code == 200
    assert f'action="/jobs/{job_id}/stop"' in page.text
    # The dashboard also surfaces a stop control while a job runs.
    assert 'action="/scan/stop"' in client.get("/").text

    gate.open()
    wait_idle(client)


def test_job_detail_renders_scan_coverage_counters(client: TestClient) -> None:
    # The job page distinguishes discovered inventory from processed work so a
    # changed count is never misread as the library size.
    store = client.app.state.store
    job_id = store.create_job("real")
    store.finish_job(
        job_id,
        JobStatus.SUCCEEDED,
        total_files=8,
        changed_files=3,
        warning_count=0,
        error_files=0,
        videos_found=20,
        subtitles_found=25,
        unwanted_subtitles=2,
        processed_files=8,
    )

    page = client.get(f"/jobs/{job_id}")

    assert page.status_code == 200
    assert "Videos found" in page.text
    assert "Subtitles found" in page.text
    assert "Unwanted subtitles" in page.text
    # The processed counter is file-level work (video phase plus subtitles), so it is
    # labelled "Files processed", not "Subtitles processed".
    assert "Files processed" in page.text
    assert "Subtitles processed" not in page.text
    # Processed work is shown against the targeted total, not as a lone number.
    assert "8 of 8" in page.text

    # The recent-jobs table carries the same coverage, including unwanted removals,
    # so a dashboard-only review can see them without opening the job.
    dashboard = client.get("/")
    assert "<th>Unwanted</th>" in dashboard.text
    assert "<th>Videos</th>" in dashboard.text


def _finish_empty(store: object, job_id: int, status: JobStatus) -> None:
    """Finish a job with empty counters, for tests that only assert on its status."""
    store.finish_job(job_id, status, total_files=0, changed_files=0, warning_count=0, error_files=0)


def test_finished_job_page_acknowledges_completion(client: TestClient) -> None:
    # A scan that finishes before its detail page renders must still show honest
    # start/completion feedback, so a fast job does not look like a silent no-op.
    store = client.app.state.store
    job_id = store.create_job("real")
    _finish_empty(store, job_id, JobStatus.SUCCEEDED)

    page = client.get(f"/jobs/{job_id}")

    assert page.status_code == 200
    assert 'id="job-notice"' in page.text
    assert "[INFO] Scan completed." in page.text


def test_job_detail_files_table_lives_in_a_scroll_wrapper(client: TestClient) -> None:
    # The job-detail files table carries long source/target paths, so it shares the
    # .table-wrap scrollable glass panel the library and dashboard tables use rather
    # than rendering as a bare table that can push the page sideways on mobile.
    store = client.app.state.store
    job_id = store.create_job("real")
    _finish_empty(store, job_id, JobStatus.SUCCEEDED)

    page = client.get(f"/jobs/{job_id}")

    assert page.status_code == 200
    wrapper, _, after = page.text.partition('<div class="table-wrap">')
    assert '<table id="job-files">' in after
    assert '<table id="job-files">' not in wrapper


def test_cancelled_job_page_reports_cancellation(client: TestClient) -> None:
    store = client.app.state.store
    job_id = store.create_job("real")
    _finish_empty(store, job_id, JobStatus.CANCELLED)

    page = client.get(f"/jobs/{job_id}")

    assert page.status_code == 200
    assert "[INFO] Scan cancelled." in page.text


def test_interrupted_job_page_reports_interruption(client: TestClient) -> None:
    store = client.app.state.store
    job_id = store.create_job("real")
    _finish_empty(store, job_id, JobStatus.INTERRUPTED)

    page = client.get(f"/jobs/{job_id}")

    assert page.status_code == 200
    assert "[WARNING] Scan interrupted before it finished." in page.text


def test_unknown_job_returns_404(client: TestClient) -> None:
    assert client.get("/api/jobs/999").status_code == 404
    assert client.get("/jobs/999").status_code == 404


def test_job_detail_distinguishes_fatal_failure_from_per_file_errors(client: TestClient) -> None:
    # A fatal job-level failure stores its message in ``error`` without touching the
    # per-file ``error_files`` count, so the summary must not label that count a
    # generic "Errors" total or the page reads "failed" with "Errors 0".
    store = client.app.state.store
    job_id = store.create_job("real")
    store.finish_job(
        job_id,
        JobStatus.FAILED,
        total_files=0,
        changed_files=0,
        warning_count=0,
        error_files=0,
        error="ffprobe not found",
    )

    page = client.get(f"/jobs/{job_id}")

    assert page.status_code == 200
    # The per-file count is labelled precisely, never a bare "Errors".
    assert "Files with errors" in page.text
    assert "<dt>Errors</dt>" not in page.text
    # The fatal failure stays visible and is marked as a job failure.
    assert "Job failed: ffprobe not found" in page.text


def test_dashboard_labels_error_column_as_files_with_errors(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    # The recent-jobs table shares the job detail wording to avoid the same ambiguity.
    assert "Files with errors" in response.text
    assert "<th>Errors</th>" not in response.text
