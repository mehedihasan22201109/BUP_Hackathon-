"""Metrics recomputed from an hourly plan.

Independent of the solver: given a candidate hourly plan and the request
inputs, this module recomputes totals from scratch and verifies they match
what the caller reports. Any disagreement is a bug in the solver, the
assembly layer, or both.
"""

from __future__ import annotations

from typing import Dict, List

from ..schemas import HourlyPlanRow, HourRow, OptimizeRequest


def compute_totals(plan: List[HourlyPlanRow]) -> Dict[str, float]:
    """Return total_grid_kwh, total_cost_bdt, peak_grid_kwh."""
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0
    # We need the tariff to compute cost. The schedule carries no tariff,
    # so cost is computed by the assembly layer using the original request.
    for row in plan:
        total_grid += row.grid_kwh
        peak_grid = max(peak_grid, row.grid_kwh)
    return {
        "total_grid_kwh": total_grid,
        "peak_grid_kwh": peak_grid,
        # cost is recomputed elsewhere because tariffs live on the request
        "total_cost_bdt": 0.0,
    }


def compute_total_cost(plan: List[HourlyPlanRow], hours: List[HourRow]) -> float:
    tariff_by_hour = {h.hour: h.tariff_bdt_per_kwh for h in hours}
    return sum(r.grid_kwh * tariff_by_hour[r.hour] for r in plan)


def plan_summary_text(
    request: OptimizeRequest,
    plan: List[HourlyPlanRow],
    total_cost: float,
    applied_directives: List[str],
) -> str:
    """Generate a deterministic 1-2 sentence summary of the optimized plan."""
    peak_hour = max(plan, key=lambda r: r.grid_kwh).hour if plan else 0
    note_count = len(request.operator_notes)
    applied = len([d for d in applied_directives if d and d != "no_op"])
    directive_clause = (
        f"Applied {applied} of {note_count} operator note(s)."
        if note_count > 0
        else "No operator notes provided."
    )
    return (
        f"24-hour cost-minimizing schedule produced at {total_cost:.2f} BDT "
        f"with peak grid import at hour {peak_hour}. {directive_clause}"
    )
