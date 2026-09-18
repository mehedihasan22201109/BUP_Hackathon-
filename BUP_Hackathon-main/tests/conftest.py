"""Pytest configuration & shared fixtures."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Make the ``app`` package importable when pytest is run from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force the mock LLM for every test unless explicitly overridden.
os.environ.setdefault("LLM_PROVIDER", "mock")

from app.config import get_settings, reset_settings_cache  # noqa: E402
from app.schemas import Battery, HourRow, OptimizeRequest  # noqa: E402


@pytest.fixture(autouse=True)
def _force_mock_provider():
    """Make every test deterministic by default."""
    os.environ["LLM_PROVIDER"] = "mock"
    reset_settings_cache()
    yield
    # Leave the env alone so other tests inherit the same defaults.


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def sample_battery() -> Battery:
    return Battery(
        capacity_kwh=200,
        initial_energy_kwh=120,
        minimum_energy_kwh=40,
        max_charge_kwh_per_hour=50,
        max_discharge_kwh_per_hour=50,
    )


@pytest.fixture
def sample_hours() -> list[HourRow]:
    out = []
    for h in range(24):
        out.append(
            HourRow(
                hour=h,
                demand_kwh=90 + (30 if 18 <= h <= 21 else 0),
                solar_kwh=60 if 9 <= h <= 15 else 0,
                tariff_bdt_per_kwh=6 + (6 if 18 <= h <= 21 else 0),
            )
        )
    return out


@pytest.fixture
def sample_request(sample_battery, sample_hours) -> OptimizeRequest:
    return OptimizeRequest(
        scenario_id="TEST-01",
        operator_notes=[
            "Keep at least 50 percent of the battery capacity from 6 PM until 9 PM for emergency operations.",
            "Library extending book-return hours next week.",
        ],
        battery=sample_battery,
        hours=sample_hours,
    )


@pytest.fixture
def public_samples() -> dict:
    p = PROJECT_ROOT / "sample_cases" / "public_sample_cases.json"
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)
