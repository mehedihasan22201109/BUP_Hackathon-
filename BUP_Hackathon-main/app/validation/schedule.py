"""Independent post-validation of an optimized schedule.

The optimizer is assumed correct, but we never trust that assumption. This
module recomputes every GridWise invariant from the returned schedule and
the request inputs, and flags any violation outside the official tolerance
(0.01 kWh / 0.01 BDT).

The result is a ``PostValidationReport`` with a boolean ``ok`` flag and a
list of human-readable violations. If ``ok`` is False, the response layer
must NOT ship the schedule to the client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..config import get_settings
from ..schemas import (
    Battery,
    BatteryAction,
    HourRow,
    HourlyPlanRow,
)
from ..optimization.directive_helpers import DirectiveState


# --------------------------------------------------------------------------- #
# Report type                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class PostValidationReport:
    ok: bool
    violations: List[str] = field(default_factory=list)
    computed_total_grid_kwh: float = 0.0
    computed_total_cost_bdt: float = 0.0
    computed_peak_grid_kwh: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "violations": list(self.violations),
            "computed_total_grid_kwh": self.computed_total_grid_kwh,
            "computed_total_cost_bdt": self.computed_total_cost_bdt,
            "computed_peak_grid_kwh": self.computed_peak_grid_kwh,
        }


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #

def validate_schedule(
    *,
    battery: Battery,
    hours: List[HourRow],
    plan: List[HourlyPlanRow],
    directives: List[dict],
) -> PostValidationReport:
    settings = get_settings()
    eps_kwh = settings.tolerance_kwh
    eps_bdt = settings.tolerance_bdt
    state = DirectiveState(directives, battery)
    violations: List[str] = []

    demand_by_hour = {h.hour: h.demand_kwh for h in hours}
    solar_by_hour = {h.hour: h.solar_kwh for h in hours}
    tariff_by_hour = {h.hour: h.tariff_bdt_per_kwh for h in hours}

    plan_by_hour: Dict[int, HourlyPlanRow] = {p.hour: p for p in plan}

    # Verify exactly 24 entries and the right hours are present
    if set(plan_by_hour.keys()) != set(range(24)):
        violations.append(
            f"hourly_plan must contain exactly hours 0..23; got "
            f"{sorted(plan_by_hour.keys())}"
        )

    # Reconstruct charge/discharge from the response layer's encoding.
    # battery_action == "charge"  -> battery_kwh is a positive charge amount
    # battery_action == "discharge" -> battery_kwh is a positive discharge amount
    charge_by_hour: Dict[int, float] = {}
    discharge_by_hour: Dict[int, float] = {}
    soc_by_hour: Dict[int, float] = {}

    for h in range(24):
        if h not in plan_by_hour:
            continue
        row = plan_by_hour[h]
        if row.battery_action == BatteryAction.CHARGE:
            charge_by_hour[h] = row.battery_kwh
            discharge_by_hour[h] = 0.0
        elif row.battery_action == BatteryAction.DISCHARGE:
            charge_by_hour[h] = 0.0
            discharge_by_hour[h] = row.battery_kwh
        elif row.battery_action == BatteryAction.IDLE:
            charge_by_hour[h] = 0.0
            discharge_by_hour[h] = 0.0
        else:  # pragma: no cover -- BatteryAction enum exhaustive
            violations.append(f"hour {h}: unknown battery_action {row.battery_action!r}")
            charge_by_hour[h] = 0.0
            discharge_by_hour[h] = 0.0
        soc_by_hour[h] = row.battery_energy_after_kwh

    # SOC continuity check
    if 0 in soc_by_hour:
        expected_soc0 = battery.initial_energy_kwh + charge_by_hour.get(0, 0.0) - discharge_by_hour.get(0, 0.0)
        if abs(soc_by_hour[0] - expected_soc0) > eps_kwh:
            violations.append(
                f"hour 0 SOC mismatch: declared {soc_by_hour[0]:.4f} "
                f"vs expected {expected_soc0:.4f}"
            )
    for h in range(1, 24):
        if h not in soc_by_hour:
            continue
        expected = (
            soc_by_hour[h - 1]
            + charge_by_hour.get(h, 0.0)
            - discharge_by_hour.get(h, 0.0)
        )
        if abs(soc_by_hour[h] - expected) > eps_kwh:
            violations.append(
                f"hour {h} SOC mismatch: declared {soc_by_hour[h]:.4f} "
                f"vs expected {expected:.4f}"
            )

    # End-of-day neutrality
    if 23 in soc_by_hour and abs(soc_by_hour[23] - battery.initial_energy_kwh) > eps_kwh:
        violations.append(
            f"end-of-day SOC {soc_by_hour[23]:.4f} != initial {battery.initial_energy_kwh:.4f}"
        )

    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    for h in range(24):
        if h not in plan_by_hour:
            continue
        row = plan_by_hour[h]
        demand = demand_by_hour.get(h, 0.0)
        solar_cap = solar_by_hour.get(h, 0.0) * state.solar_factor(h)
        reserve = state.reserve_floor(h)

        # (1) Energy balance
        lhs = row.grid_kwh + row.solar_used_kwh + discharge_by_hour[h]
        rhs = demand + charge_by_hour[h]
        if abs(lhs - rhs) > eps_kwh:
            violations.append(
                f"hour {h} energy balance off: "
                f"grid+sol+dis={lhs:.4f} vs demand+chg={rhs:.4f}"
            )

        # (2) Solar cap
        if row.solar_used_kwh - solar_cap > eps_kwh:
            violations.append(
                f"hour {h} solar_used {row.solar_used_kwh:.4f} "
                f"exceeds effective cap {solar_cap:.4f}"
            )

        # (3) SOC bounds
        if soc_by_hour[h] - battery.capacity_kwh > eps_kwh:
            violations.append(
                f"hour {h} SOC {soc_by_hour[h]:.4f} exceeds capacity {battery.capacity_kwh:.4f}"
            )
        if soc_by_hour[h] - reserve < -eps_kwh:
            violations.append(
                f"hour {h} SOC {soc_by_hour[h]:.4f} below reserve {reserve:.4f}"
            )

        # (4) Rate limits
        if charge_by_hour[h] - battery.max_charge_kwh_per_hour > eps_kwh:
            violations.append(
                f"hour {h} charge {charge_by_hour[h]:.4f} exceeds rate limit "
                f"{battery.max_charge_kwh_per_hour:.4f}"
            )
        if discharge_by_hour[h] - battery.max_discharge_kwh_per_hour > eps_kwh:
            violations.append(
                f"hour {h} discharge {discharge_by_hour[h]:.4f} exceeds rate limit "
                f"{battery.max_discharge_kwh_per_hour:.4f}"
            )

        # (5) Directive windows
        if h in state.no_charge_hours and charge_by_hour[h] > eps_kwh:
            violations.append(
                f"hour {h} violates no_charge_window (charge={charge_by_hour[h]:.4f})"
            )
        if h in state.no_discharge_hours and discharge_by_hour[h] > eps_kwh:
            violations.append(
                f"hour {h} violates no_discharge_window (discharge={discharge_by_hour[h]:.4f})"
            )
        cap = state.max_grid_for(h)
        if cap is not None and row.grid_kwh - cap > eps_kwh:
            violations.append(
                f"hour {h} grid_kwh {row.grid_kwh:.4f} exceeds max_grid cap {cap:.4f}"
            )

        # (6) battery_kwh must match direction
        if row.battery_action == BatteryAction.IDLE and row.battery_kwh > eps_kwh:
            violations.append(
                f"hour {h} idle action has non-zero battery_kwh {row.battery_kwh:.4f}"
            )
        if row.battery_action in (BatteryAction.CHARGE, BatteryAction.DISCHARGE) and row.battery_kwh < 0:
            violations.append(
                f"hour {h} {row.battery_action.value} has negative battery_kwh {row.battery_kwh:.4f}"
            )

        # Totals
        total_grid += row.grid_kwh
        total_cost += row.grid_kwh * tariff_by_hour.get(h, 0.0)
        peak_grid = max(peak_grid, row.grid_kwh)

    # Totals vs declared
    if abs(total_grid - sum(p.grid_kwh for p in plan)) > eps_kwh:
        violations.append("total_grid_kwh mismatch with hourly_plan sum")

    return PostValidationReport(
        ok=not violations,
        violations=violations,
        computed_total_grid_kwh=total_grid,
        computed_total_cost_bdt=total_cost,
        computed_peak_grid_kwh=peak_grid,
    )
