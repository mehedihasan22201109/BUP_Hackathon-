"""Smoke tests for GET /health."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_expected_payload():
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "gridwise-llm-energy-optimizer"
    assert "version" in body


def test_health_endpoint_present_in_openapi():
    app = create_app()
    schema = app.openapi()
    assert "/health" in schema["paths"]
    assert "get" in schema["paths"]["/health"]
