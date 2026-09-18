"""Independent post-validation tests."""

from __future__ import annotations

from typing import List

from app.schemas import Battery, BatteryAction, HourRow, HourlyPlanRow
from app.validation.directives import normalize_entries
from app.validation.schedule import validate_schedule


def _no_op_directives():
    return normalize_entries(
        [{"note_index": 0, "directive_type": "no_op", "applies": False,
          "structured_adjustment": None, "explanation": "n"}],
        ["n"],
    )


def _battery():
    return Battery(
        capacity_kwh=200,
        initial_energy_kwh=120,
        minimum_energy_kwh=40,
        max_charge_kwh_per_hour=50,
        max_discharge_kwh_per_hour=50,
    )


def _hours():
    out = []
    for h in range(24):
        out.append(
            HourRow(
                hour=h,
                demand_kwh=90,
                solar_kwh=60 if 9 <= h <= 15 else 0,
                tariff_bdt_per_kwh=6,
            )
        )
    return out


def _balanced_plan():
    """Flat feasible plan: demand=90 everywhere.

    * In solar window (9..15): grid=30, solar=60   (30 + 60 = 90)
    * Out of solar window: grid=90, solar=0       (90 + 0 = 90)
    Battery idle everywhere; SOC stays at 120.
    """
    plan: List[HourlyPlanRow] = []
    for h in range(24):
        if 9 <= h <= 15:
            grid = 30.0
            solar = 60.0
        else:
            grid = 90.0
            solar = 0.0
        plan.append(
            HourlyPlanRow(
                hour=h,
                grid_kwh=grid,
                solar_used_kwh=solar,
                battery_action=BatteryAction.IDLE,
                battery_kwh=0.0,
                battery_energy_after_kwh=120.0,
            )
        )
    return plan


def test_post_validation_passes_on_feasible_plan():
    b = _battery()
    plan = _balanced_plan()
    report = validate_schedule(
        battery=b, hours=_hours(), plan=plan, directives=_no_op_directives()
    )
    assert report.ok, report.violations


def test_post_validation_flags_energy_balance_violation():
    b = _battery()
    plan = _balanced_plan()
    plan[5] = plan[5].model_copy(update={"grid_kwh": plan[5].grid_kwh + 9999.0})
    report = validate_schedule(
        battery=b, hours=_hours(), plan=plan, directives=_no_op_directives()
    )
    assert not report.ok
    assert any("energy balance" in v for v in report.violations)


def test_post_validation_flags_soc_below_minimum():
    b = _battery()
    plan = _balanced_plan()
    plan[3] = plan[3].model_copy(update={"battery_energy_after_kwh": 0.0})
    report = validate_schedule(
        battery=b, hours=_hours(), plan=plan, directives=_no_op_directives()
    )
    assert not report.ok
    assert any("SOC" in v or "reserve" in v for v in report.violations)


def test_post_validation_flags_end_of_day_neutrality_violation():
    b = _battery()
    plan = _balanced_plan()
    plan[23] = plan[23].model_copy(update={"battery_energy_after_kwh": 50.0})
    report = validate_schedule(
        battery=b, hours=_hours(), plan=plan, directives=_no_op_directives()
    )
    assert not report.ok
    assert any("end-of-day" in v for v in report.violations)


def test_post_validation_flags_solar_cap_violation():
    b = _battery()
    plan = _balanced_plan()
    plan[10] = plan[10].model_copy(update={"solar_used_kwh": 9999.0})
    report = validate_schedule(
        battery=b, hours=_hours(), plan=plan, directives=_no_op_directives()
    )
    assert not report.ok
    assert any("solar_used" in v for v in report.violations)


def test_post_validation_flags_no_charge_window_violation():
    b = _battery()
    directives = normalize_entries(
        [{
            "note_index": 0, "directive_type": "no_charge_window",
            "applies": True, "structured_adjustment": {"hours": [3, 4, 5]},
            "explanation": "n",
        }],
        ["n"],
        battery=b,
    )
    plan: List[HourlyPlanRow] = []
    for h in range(24):
        solar = 60 if 9 <= h <= 15 else 0
        plan.append(
            HourlyPlanRow(
                hour=h,
                grid_kwh=80.0,
                solar_used_kwh=solar,
                battery_action=BatteryAction.CHARGE,
                battery_kwh=10.0,
                battery_energy_after_kwh=120.0,
            )
        )
    report = validate_schedule(
        battery=b, hours=_hours(), plan=plan, directives=directives
    )
    assert not report.ok
    assert any("no_charge_window" in v for v in report.violations)


def test_post_validation_flags_max_grid_window_violation():
    b = _battery()
    directives = normalize_entries(
        [{
            "note_index": 0, "directive_type": "max_grid_window",
            "applies": True, "structured_adjustment": {"hours": [10, 11], "max_grid_kwh": 10.0},
            "explanation": "n",
        }],
        ["n"],
        battery=b,
    )
    plan = _balanced_plan()
    report = validate_schedule(
        battery=b, hours=_hours(), plan=plan, directives=directives
    )
    assert not report.ok
    assert any("max_grid" in v for v in report.violations)
