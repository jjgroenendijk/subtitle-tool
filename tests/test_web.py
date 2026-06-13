"""Tests for the web application stub."""

from __future__ import annotations

from fastapi.testclient import TestClient

from subtitle_tool import __version__
from subtitle_tool.web import create_app


def test_health_endpoint_reports_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
