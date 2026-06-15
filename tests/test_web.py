"""Tests for the web app: pages, JSON API, config round-trip, and background scans."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from subtitle_tool import __version__
from subtitle_tool.config import BootstrapSettings, load_config, save_config
from subtitle_tool.config.models import Config
from subtitle_tool.web import create_app


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


@pytest.fixture
def client(config_dir: Path) -> Iterator[TestClient]:
    app = create_app(BootstrapSettings(CONFIG_DIR=config_dir))
    # The context manager runs the lifespan, binding the broker's event loop.
    with TestClient(app) as test_client:
        yield test_client


def build_library(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Movie (2020).mkv").write_text("video", encoding="utf-8")
    (root / "Movie (2020).fr.ass").write_text(
        "[Script Info]\nScriptType: v4.00+\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Bonjour le monde\n",
        encoding="utf-8",
    )


def configure_media(config_dir: Path, media: Path) -> None:
    save_config(
        Config.model_validate({"scan": {"media_paths": [str(media)]}}),
        config_dir / "config.toml",
    )


def wait_idle(client: TestClient, timeout: float = 5.0) -> None:
    worker = client.app.state.worker
    deadline = time.monotonic() + timeout
    while worker.is_busy:
        if time.monotonic() > deadline:
            raise AssertionError("worker did not finish")
        time.sleep(0.01)


def test_health_endpoint_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_dashboard_renders(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "Scan now" in response.text


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
    # Languages are multi-selects with readable, code-bearing labels, not textareas.
    assert '<select id="extraction.languages" name="extraction.languages" multiple' in response.text
    assert 'id="language.filter.wanted_languages"' in response.text
    assert "English (en)" in response.text


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
    assert detail["files"][0]["changed"]


def test_library_page_renders_indexed_videos(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    build_library(media)
    save_config(
        Config.model_validate(
            {
                "scan": {"media_paths": [str(media)]},
                "language": {"filter": {"enabled": True, "wanted_languages": ["en", "nl"]}},
            }
        ),
        config_dir / "config.toml",
    )

    # Empty before any scan populates the index.
    empty = client.get("/library")
    assert empty.status_code == 200
    assert "No indexed videos yet" in empty.text

    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)

    page = client.get("/library")
    assert page.status_code == 200
    assert "Movie (2020).mkv" in page.text

    library = client.get("/api/library").json()
    assert len(library) == 1
    entry = library[0]
    assert entry["path"].endswith("Movie (2020).mkv")
    # The French subtitle is indexed; the wanted en and nl are both missing.
    assert "fr" in entry["languages"]
    assert entry["missing_languages"] == ["en", "nl"]


def test_scan_button_redirects_to_job(client: TestClient, config_dir: Path, tmp_path: Path) -> None:
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    response = client.post("/scan", data={"mode": "dry-run"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs/")
    wait_idle(client)


def test_stop_routes_redirect(client: TestClient) -> None:
    # No job is running, so a stop is a safe no-op that still redirects back.
    dashboard_stop = client.post("/scan/stop", follow_redirects=False)
    assert dashboard_stop.status_code == 303
    assert dashboard_stop.headers["location"] == "/"

    job_stop = client.post("/jobs/1/stop", follow_redirects=False)
    assert job_stop.status_code == 303
    assert job_stop.headers["location"] == "/jobs/1"


def test_cancel_api_409_when_no_job_running(client: TestClient) -> None:
    assert client.post("/api/jobs/999/cancel").status_code == 409


def test_cancel_api_stops_running_job(
    client: TestClient, config_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    import threading

    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    import subtitle_tool.jobs.worker as worker_module

    entered = threading.Event()
    gate = threading.Event()
    real_scan = worker_module.scan

    def blocking_scan(cfg):
        entered.set()
        gate.wait(timeout=5.0)
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)

    created = client.post("/api/jobs", json={"mode": "real"})
    job_id = created.json()["id"]
    assert entered.wait(timeout=5.0)

    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelling"

    gate.set()
    wait_idle(client)

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "cancelled"
    assert detail["finished_at"] is not None


def test_running_job_page_shows_stop_button(
    client: TestClient, config_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    import threading

    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    import subtitle_tool.jobs.worker as worker_module

    entered = threading.Event()
    gate = threading.Event()
    real_scan = worker_module.scan

    def blocking_scan(cfg):
        entered.set()
        gate.wait(timeout=5.0)
        return real_scan(cfg)

    monkeypatch.setattr(worker_module, "scan", blocking_scan)

    created = client.post("/api/jobs", json={"mode": "real"})
    job_id = created.json()["id"]
    assert entered.wait(timeout=5.0)

    page = client.get(f"/jobs/{job_id}")
    assert page.status_code == 200
    assert f'action="/jobs/{job_id}/stop"' in page.text
    # The dashboard also surfaces a stop control while a job runs.
    assert 'action="/scan/stop"' in client.get("/").text

    gate.set()
    wait_idle(client)


def test_unknown_job_returns_404(client: TestClient) -> None:
    assert client.get("/api/jobs/999").status_code == 404
    assert client.get("/jobs/999").status_code == 404
