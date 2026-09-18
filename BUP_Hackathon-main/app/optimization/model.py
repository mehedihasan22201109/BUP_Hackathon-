"""PuLP LP model for the 24-hour GridWise schedule.

Decision variables per hour h in 0..23:

    grid[h]              >= 0          -- grid import (kWh)
    solar_used[h]        >= 0          -- solar consumed (kWh)
    charge[h]            >= 0          -- energy charged into battery (kWh)
    discharge[h]         >= 0          -- energy discharged from battery (kWh)
    soc[h]               continuous    -- battery SOC after hour h (kWh)

The model is a continuous LP. The "battery_action" label (charge/discharge/idle)
is derived post-solve from the optimal (charge, discharge) values using a small
tolerance, so the solver does not have to know about integer actions.

Objective
---------
    minimize SUM_h grid[h] * tariff[h]

Constraints
-----------
For every h in 0..23:

  (1) Energy balance:
        grid[h] + solar_used[h] + discharge[h] = demand[h] + charge[h]

  (2) Solar cap (after any solar_reduction factor is applied):
        solar_used[h] <= solar[h] * factor[h]

  (3) Battery SOC dynamics:
        soc[h] = soc[h-1] + charge[h] * eta_c - discharge[h] / eta_d
      (no efficiency losses in v1.0 -- documented in the README)

  (4) Battery bounds:
        reserve_floor[h] <= soc[h] <= capacity
        where reserve_floor[h] = max(battery.minimum_energy_kwh,
                                     active_reserve_window[h])

  (5) Charge / discharge rate limits:
        charge[h]    <= battery.max_charge_kwh_per_hour
        discharge[h] <= battery.max_discharge_kwh_per_hour

  (6) Directive-driven windows:
        if h in no_charge_window:    charge[h]    = 0
        if h in no_discharge_window: discharge[h] = 0
        if h in max_grid_window:     grid[h]     <= max_grid[h]

Boundary:
        soc[-1] = battery.initial_energy_kwh
        soc[23] = battery.initial_energy_kwh   (end-of-day neutrality)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

import pulp

from ..schemas import Battery, HourRow
from .directive_helpers import DirectiveState

logger = logging.getLogger(__name__)


@dataclass
class ModelArtifacts:
    """The variable containers the solver returns."""

    grid: Dict[int, pulp.LpVariable] = field(default_factory=dict)
    solar_used: Dict[int, pulp.LpVariable] = field(default_factory=dict)
    charge: Dict[int, pulp.LpVariable] = field(default_factory=dict)
    discharge: Dict[int, pulp.LpVariable] = field(default_factory=dict)
    soc: Dict[int, pulp.LpVariable] = field(default_factory=dict)


def build_model(
    *,
    battery: Battery,
    hours: List[HourRow],
    directives: DirectiveState,
    solver_timeout_seconds: int = 10,
    solver_msg: bool = False,
) -> tuple[pulp.LpProblem, ModelArtifacts]:
    """Build the PuLP model and return it plus the variable handles."""
    hours_sorted = sorted(hours, key=lambda h: h.hour)
    demand = {h.hour: h.demand_kwh for h in hours_sorted}
    solar_avail = {h.hour: h.solar_kwh for h in hours_sorted}
    tariff = {h.hour: h.tariff_bdt_per_kwh for h in hours_sorted}
    solar_factor = {h.hour: directives.solar_factor(h.hour) for h in hours_sorted}

    prob = pulp.LpProblem("gridwise_24h", pulp.LpMinimize)
    artifacts = ModelArtifacts()

    for h in range(24):
        artifacts.grid[h] = pulp.LpVariable(f"grid_{h}", lowBound=0)
        artifacts.solar_used[h] = pulp.LpVariable(f"solar_used_{h}", lowBound=0)
        artifacts.charge[h] = pulp.LpVariable(f"charge_{h}", lowBound=0)
        artifacts.discharge[h] = pulp.LpVariable(f"discharge_{h}", lowBound=0)
        artifacts.soc[h] = pulp.LpVariable(f"soc_{h}", lowBound=0, upBound=battery.capacity_kwh)

    # ---- Objective ----
    # Primary: minimize total grid electricity cost (spec §5.2).
    # Secondary: minimize peak grid kWh as a tie-breaker so that the solver
    # picks the lowest-peak schedule among cost-equivalent optima. The
    # tie-breaker weight (PEAK_WEIGHT) is intentionally tiny: any cost
    # difference of 1e-3 BDT dominates it, so cost ordering is preserved.
    # This makes the chosen schedule deterministic and reproducible across
    # cases where multiple schedules achieve the same minimum cost.
    PEAK_WEIGHT = 1e-3
    peak = pulp.LpVariable("peak_grid_kwh", lowBound=0)
    for h in range(24):
        prob += peak >= artifacts.grid[h]
    prob += (
        pulp.lpSum(artifacts.grid[h] * tariff[h] for h in range(24))
        + PEAK_WEIGHT * peak
    )

    # ---- Constraints ----
    # SOC continuity
    prob += artifacts.soc[0] == battery.initial_energy_kwh + artifacts.charge[0] - artifacts.discharge[0]
    for h in range(1, 24):
        prob += (
            artifacts.soc[h]
            == artifacts.soc[h - 1] + artifacts.charge[h] - artifacts.discharge[h]
        )
    # End-of-day neutrality
    prob += artifacts.soc[23] == battery.initial_energy_kwh

    for h in range(24):
        # (1) Energy balance
        prob += (
            artifacts.grid[h] + artifacts.solar_used[h] + artifacts.discharge[h]
            == demand[h] + artifacts.charge[h]
        )
        # (2) Solar cap
        prob += artifacts.solar_used[h] <= solar_avail[h] * solar_factor[h]
        # (4) Battery bounds with reserve window override
        prob += artifacts.soc[h] >= directives.reserve_floor(h)

        # (5) Rate limits
        prob += artifacts.charge[h] <= battery.max_charge_kwh_per_hour
        prob += artifacts.discharge[h] <= battery.max_discharge_kwh_per_hour

        # (6) Directive windows
        if h in directives.no_charge_hours:
            prob += artifacts.charge[h] == 0
        if h in directives.no_discharge_hours:
            prob += artifacts.discharge[h] == 0
        if h in directives.max_grid_hours:
            cap = directives.max_grid_for(h)
            if cap is not None:
                prob += artifacts.grid[h] <= cap

    # Solver
    solver = pulp.PULP_CBC_CMD(
        timeLimit=solver_timeout_seconds,
        msg=solver_msg,
    )
    prob.solver = solver
    return prob, artifacts
