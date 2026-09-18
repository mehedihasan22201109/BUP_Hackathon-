"""High-level LP solver wrapper.

The solver module is the only place that talks to PuLP directly. It:
  * builds the model
  * invokes PuLP's bundled CBC solver
  * extracts variable values
  * maps them into the canonical HourlyPlanRow schedule
  * returns an ``OptimizerSolution`` plus the directive list (for the
    response assembly layer to reuse)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import pulp

from ..config import get_settings
from ..exceptions import OptimizerError
from ..schemas import Battery, BatteryAction, HourRow, OptimizerSolution
from .directive_helpers import DirectiveState
from .model import build_model

logger = logging.getLogger(__name__)


_ACTION_EPS = 1e-6


def _action_for(charge: float, discharge: float) -> Tuple[BatteryAction, float]:
    """Translate (charge, discharge) into (action, kWh) at the response layer.

    PuLP sometimes emits simultaneous charge + discharge when the model
    includes degenerate ties (LP alternates between two equal-cost optima).
    The schedule layer must collapse these into the *net* action so that
    the validator can reconstruct SOC from ``charge - discharge``.
    """
    net = charge - discharge
    if net > _ACTION_EPS:
        return BatteryAction.CHARGE, net
    if -net > _ACTION_EPS:
        return BatteryAction.DISCHARGE, -net
    return BatteryAction.IDLE, 0.0


def solve(
    *,
    battery: Battery,
    hours: List[HourRow],
    directives: List[dict],
) -> Tuple[OptimizerSolution, List[dict]]:
    """Build, solve, and extract.

    Returns ``(OptimizerSolution, directives)``. Directives are echoed back
    because the response layer needs the validated list verbatim.

    Raises ``OptimizerError`` on infeasibility or solver failure.
    """
    settings = get_settings()
    state = DirectiveState(directives, battery)
    prob, vars_ = build_model(
        battery=battery,
        hours=hours,
        directives=state,
        solver_timeout_seconds=settings.solver_timeout_seconds,
        solver_msg=settings.solver_msg,
    )

    status = prob.solve(pulp.PULP_CBC_CMD(
        timeLimit=settings.solver_timeout_seconds,
        msg=settings.solver_msg,
    ))

    status_str = pulp.LpStatus[status]
    logger.info("LP status: %s", status_str)

    if status_str not in ("Optimal",):
        raise OptimizerError(
            f"Solver did not return an optimal solution (status={status_str}).",
            details={"status": status_str},
        )

    # Extract variable values with the standard 1e-6 rounding tolerance that
    # PuLP applies to LpVariable.value().
    grid = {h: float(vars_.grid[h].value() or 0.0) for h in range(24)}
    solar_used = {h: float(vars_.solar_used[h].value() or 0.0) for h in range(24)}
    charge = {h: float(vars_.charge[h].value() or 0.0) for h in range(24)}
    discharge = {h: float(vars_.discharge[h].value() or 0.0) for h in range(24)}
    soc = {h: float(vars_.soc[h].value() or 0.0) for h in range(24)}

    total_grid = sum(grid.values())
    peak_grid = max(grid.values()) if grid else 0.0
    tariff_by_hour = {h.hour: h.tariff_bdt_per_kwh for h in hours}
    total_cost = sum(grid[h] * tariff_by_hour[h] for h in range(24))

    return (
        OptimizerSolution(
            grid=grid,
            solar_used=solar_used,
            battery_charge=charge,
            battery_discharge=discharge,
            battery_energy_after=soc,
            total_grid_kwh=total_grid,
            total_cost_bdt=total_cost,
            peak_grid_kwh=peak_grid,
        ),
        directives,
    )


def build_hourly_plan(
    solution: OptimizerSolution,
) -> List[Tuple[int, BatteryAction, float, float, float, float]]:
    """Turn the raw solver solution into the 6-tuples the response layer needs.

    Each tuple is:
        (hour, battery_action, battery_kwh, grid_kwh, solar_used_kwh, soc_after)
    """
    out: List[Tuple[int, BatteryAction, float, float, float, float]] = []
    for h in range(24):
        action, kwh = _action_for(
            solution.battery_charge[h], solution.battery_discharge[h]
        )
        out.append(
            (
                h,
                action,
                kwh,
                solution.grid[h],
                solution.solar_used[h],
                solution.battery_energy_after[h],
            )
        )
    return out

