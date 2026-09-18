"""HTTP-layer integration tests using FastAPI's TestClient."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app())


def test_health_endpoint_returns_ok():
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "gridwise-llm-energy-optimizer"
    assert "version" in body


def test_optimize_energy_endpoint_runs_with_mock(sample_request):
    r = client.post("/optimize-energy", json=sample_request.model_dump())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scenario_id"] == sample_request.scenario_id
    assert len(body["hourly_plan"]) == 24
    assert len(body["directive_interpretation"]) == len(sample_request.operator_notes)
    assert body["total_cost_bdt"] >= 0
    assert body["total_grid_kwh"] >= 0
    assert body["peak_grid_kwh"] >= 0
    assert "plan_summary" in body and body["plan_summary"]


def test_optimize_energy_rejects_missing_hours(sample_battery):
    payload = {
        "scenario_id": "BAD-01",
        "operator_notes": ["x"],
        "battery": sample_battery.model_dump(),
        "hours": [{"hour": i, "demand_kwh": 10, "solar_kwh": 0,
                   "tariff_bdt_per_kwh": 5} for i in range(23)],  # only 23
    }
    r = client.post("/optimize-energy", json=payload)
    assert r.status_code == 422


def test_optimize_energy_rejects_battery_initial_above_capacity(sample_battery):
    bad_battery = sample_battery.model_copy(
        update={"initial_energy_kwh": sample_battery.capacity_kwh + 50}
    )
    payload = {
        "scenario_id": "BAD-02",
        "operator_notes": ["x"],
        "battery": bad_battery.model_dump(),
        "hours": [{"hour": i, "demand_kwh": 10, "solar_kwh": 0,
                   "tariff_bdt_per_kwh": 5} for i in range(24)],
    }
    r = client.post("/optimize-energy", json=payload)
    assert r.status_code == 422


def test_optimize_energy_rejects_extra_fields(sample_request):
    payload = sample_request.model_dump()
    payload["rogue_field"] = "not allowed"
    r = client.post("/optimize-energy", json=payload)
    assert r.status_code == 422


def test_openapi_contains_documented_endpoints():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert "/health" in spec["paths"]
    assert "/optimize-energy" in spec["paths"]
