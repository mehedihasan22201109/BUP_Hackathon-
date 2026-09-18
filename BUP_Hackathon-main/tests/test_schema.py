"""Pydantic schema validation tests.

These exercise the request/response schemas without invoking the optimizer
or the LLM.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    Battery,
    DirectiveType,
    HourRow,
    OptimizeRequest,
    OptimizeResponse,
)


def test_battery_valid():
    b = Battery(
        capacity_kwh=200,
        initial_energy_kwh=120,
        minimum_energy_kwh=40,
        max_charge_kwh_per_hour=50,
        max_discharge_kwh_per_hour=50,
    )
    assert b.capacity_kwh == 200


def test_battery_initial_above_capacity_rejected():
    with pytest.raises(ValidationError):
        Battery(
            capacity_kwh=100,
            initial_energy_kwh=150,
            minimum_energy_kwh=10,
            max_charge_kwh_per_hour=10,
            max_discharge_kwh_per_hour=10,
        )


def test_battery_minimum_above_capacity_rejected():
    with pytest.raises(ValidationError):
        Battery(
            capacity_kwh=100,
            initial_energy_kwh=50,
            minimum_energy_kwh=150,
            max_charge_kwh_per_hour=10,
            max_discharge_kwh_per_hour=10,
        )


def test_optimize_request_requires_exactly_24_hours(sample_battery):
    rows = [
        HourRow(hour=h, demand_kwh=90, solar_kwh=0, tariff_bdt_per_kwh=6)
        for h in range(24)
    ]
    rows = rows[:-1]  # 23 entries
    with pytest.raises(ValidationError):
        OptimizeRequest(
            scenario_id="X",
            operator_notes=["note"],
            battery=sample_battery,
            hours=rows,
        )


def test_optimize_request_rejects_duplicate_hours(sample_battery):
    rows = [
        HourRow(hour=0, demand_kwh=10, solar_kwh=0, tariff_bdt_per_kwh=5),
        HourRow(hour=0, demand_kwh=20, solar_kwh=0, tariff_bdt_per_kwh=6),
    ] + [
        HourRow(hour=h, demand_kwh=90, solar_kwh=0, tariff_bdt_per_kwh=6)
        for h in range(2, 24)
    ]
    with pytest.raises(ValidationError):
        OptimizeRequest(
            scenario_id="X",
            operator_notes=["note"],
            battery=sample_battery,
            hours=rows,
        )


def test_directive_type_enum_is_strict():
    for value in (
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    ):
        assert DirectiveType(value).value == value

    with pytest.raises(ValueError):
        DirectiveType("made_up_directive")
