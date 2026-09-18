"""Optimizer service: glue between HTTP layer, LLM, validator, solver.

This module owns the end-to-end flow:

    request -> LLM -> directive validation -> LP solve -> post-validation
            -> assemble OptimizeResponse

It deliberately raises typed exceptions (``LLMError``, ``OptimizerError``,
``PostValidationError``, ``DirectiveValidationError``) so the FastAPI layer
can map them to precise HTTP status codes without inspecting strings.
"""

from __future__ import annotations

import logging
from typing import List

from ..llm.fallback_parser import fallback_parse
from ..llm.interpreter import NoteInterpreter, build_default_interpreter
from ..optimization.metrics import compute_total_cost, plan_summary_text
from ..optimization.solver import build_hourly_plan, solve
from ..schemas import (
    DirectiveInterpretation,
    HourlyPlanRow,
    OptimizeRequest,
    OptimizeResponse,
    StructuredAdjustment,
)
from ..validation.directives import normalize_entries
from ..validation.schedule import validate_schedule

logger = logging.getLogger(__name__)


class OptimizerService:
    """Owns one NoteInterpreter; safe to construct at app startup."""

    def __init__(self, interpreter: NoteInterpreter | None = None) -> None:
        self._interpreter = interpreter or build_default_interpreter()

    @property
    def interpreter(self) -> NoteInterpreter:
        return self._interpreter

    def optimize(self, request: OptimizeRequest) -> OptimizeResponse:
        """Run the full pipeline for one request."""
        # 1. LLM interpretation (with deterministic validator inside).
        raw_entries = self._interpreter.interpret(request.operator_notes)

        # 1b. Deterministic fallback: when the LLM misclassifies a note as
        #     no_op or returns empty hours, the fallback parser re-reads
        #     the note text and emits a safe directive. The fallback is
        #     generic -- it does not consult any sample-specific phrasing.
        raw_entries = _apply_fallback(
            raw_entries,
            request.operator_notes,
            capacity_kwh=request.battery.capacity_kwh,
        )

        # 2. Normalize against the request -- this guarantees one safe entry
        #    per note, in order, with the correct structured_adjustment shape.
        directives = normalize_entries(
            raw_entries, request.operator_notes, battery=request.battery
        )

        # 3. Solve the LP.
        solution, _ = solve(
            battery=request.battery,
            hours=request.hours,
            directives=directives,
        )

        # 4. Build the response-shaped schedule from the solver solution.
        tuples = build_hourly_plan(solution)
        plan_rows: List[HourlyPlanRow] = []
        for hour, action, kwh, grid, solar, soc_after in tuples:
            plan_rows.append(
                HourlyPlanRow(
                    hour=hour,
                    grid_kwh=grid,
                    solar_used_kwh=solar,
                    battery_action=action,
                    battery_kwh=kwh,
                    battery_energy_after_kwh=soc_after,
                )
            )

        # 5. Independent post-validation.
        report = validate_schedule(
            battery=request.battery,
            hours=request.hours,
            plan=plan_rows,
            directives=directives,
        )
        if not report.ok:
            logger.error("Post-validation failed: %s", report.violations)
            from ..exceptions import PostValidationError
            raise PostValidationError(
                "Optimized schedule failed independent validation",
                details={"violations": report.violations},
            )

        # 6. Assemble the response.
        #    Use the recomputed totals so the response is self-consistent.
        total_grid = report.computed_total_grid_kwh
        total_cost = report.computed_total_cost_bdt
        peak_grid = report.computed_peak_grid_kwh

        applied_types = [
            d["directive_type"] for d in directives if d.get("applies")
        ]
        summary = plan_summary_text(
            request=request,
            plan=plan_rows,
            total_cost=total_cost,
            applied_directives=applied_types,
        )

        interpretation_rows: List[DirectiveInterpretation] = []
        for d in directives:
            adj = d.get("structured_adjustment")
            adj_model = (
                StructuredAdjustment(**adj) if isinstance(adj, dict) else None
            )
            interpretation_rows.append(
                DirectiveInterpretation(
                    note_index=int(d["note_index"]),
                    applies=bool(d.get("applies", False)),
                    directive_type=d["directive_type"],
                    structured_adjustment=adj_model,
                    explanation=str(d.get("explanation", "")).strip()
                    or "Operator directive processed.",
                )
            )

        return OptimizeResponse(
            scenario_id=request.scenario_id,
            directive_interpretation=interpretation_rows,
            hourly_plan=plan_rows,
            total_grid_kwh=total_grid,
            total_cost_bdt=total_cost,
            peak_grid_kwh=peak_grid,
            plan_summary=summary,
        )

def _apply_fallback(
    raw_entries: list,
    operator_notes: list,
    *,
    capacity_kwh: float | None = None,
) -> list:
    """Recover from LLM misclassifications using the deterministic fallback.

    Three recovery rules:

      R1. LLM says no_op but the fallback detects a real directive -- use
          the fallback result. Catches the "downgrade to no_op" failure
          mode documented in fallback_parser.py.
      R2. LLM says applies=true with empty hours while the fallback has
          non-empty hours -- use the fallback hours. Catches the
          "zeroed constraint" failure mode.
      R3. LLM emits factor=0.5 default for solar_reduction but the note
          text contains an explicit percentage -- use the fallback
          factor.

    Each rule fires only when the fallback is strictly more informative
    than the LLM output, so the fallback never silently downgrades.
    """
    if not operator_notes:
        return raw_entries
    by_idx = {}
    for e in raw_entries or []:
        if isinstance(e, dict):
            try:
                ni = int(e.get("note_index", -1))
            except (TypeError, ValueError):
                continue
            by_idx.setdefault(ni, e)
    for idx, note in enumerate(operator_notes):
        if not isinstance(note, str):
            continue
        fb = fallback_parse(note, idx, capacity_kwh=capacity_kwh)
        llm = by_idx.get(idx)
        if not isinstance(llm, dict):
            by_idx[idx] = fb
            continue
        llm_type = llm.get("directive_type")
        fb_type = fb.get("directive_type")
        llm_applies = bool(llm.get("applies", False))
        fb_applies = bool(fb.get("applies", False))
        llm_adj = llm.get("structured_adjustment") or {}
        fb_adj = fb.get("structured_adjustment") or {}

        # R1a: LLM no_op but fallback found a directive.
        if not llm_applies and fb_applies:
            by_idx[idx] = fb
            continue

        # R1b: LLM and fallback disagree on type, AND fallback has a
        # non-default numeric (factor, cap, minimum) -- the LLM misclassified
        # the note. Trust the fallback.
        if (
            llm_applies
            and fb_applies
            and llm_type != fb_type
            and fb_type != "no_op"
        ):
            fb_adj_check = fb_adj
            has_evidence = (
                fb_adj_check.get("factor") not in (None, 0.5)
                or fb_adj_check.get("minimum_energy_kwh") not in (None, 0)
                or fb_adj_check.get("max_grid_kwh") not in (None, 0)
            )
            if has_evidence:
                by_idx[idx] = fb
                continue

        if not fb_applies:
            continue

        # R4: same directive type, but LLM numeric is zero/missing while
        # fallback has a real number. Use the fallback's numeric.
        if llm_type == fb_type and fb_applies and llm_type != "no_op":
            if llm_type == "max_grid_window":
                llm_cap = llm_adj.get("max_grid_kwh")
                fb_cap = fb_adj.get("max_grid_kwh")
                if llm_cap in (None, 0.0) and fb_cap not in (None, 0.0):
                    llm_adj = {**llm_adj, "max_grid_kwh": fb_cap}
                    llm["structured_adjustment"] = llm_adj
                    by_idx[idx] = llm
                    continue
            elif llm_type == "minimum_battery_reserve":
                llm_min = llm_adj.get("minimum_energy_kwh")
                fb_min = fb_adj.get("minimum_energy_kwh")
                if llm_min in (None, 0.0) and fb_min not in (None, 0.0):
                    llm_adj = {**llm_adj, "minimum_energy_kwh": fb_min}
                    llm["structured_adjustment"] = llm_adj
                    by_idx[idx] = llm
                    continue

        # R2: LLM hours empty, fallback hours populated.
        llm_hours = llm_adj.get("hours") or []
        fb_hours = fb_adj.get("hours") or []
        if isinstance(llm_hours, list) and isinstance(fb_hours, list):
            if not llm_hours and fb_hours:
                llm_adj = {**llm_adj, "hours": fb_hours}
                llm["structured_adjustment"] = llm_adj
                by_idx[idx] = llm

        # R3: solar_reduction factor sanity.
        if (
            llm_type == "solar_reduction"
            and fb_type == "solar_reduction"
            and fb_adj.get("factor") is not None
            and fb_adj.get("factor") != 0.5
            and llm_adj.get("factor") in (None, 0.5)
        ):
            llm_adj = {**llm_adj, "factor": fb_adj["factor"]}
            llm["structured_adjustment"] = llm_adj
            by_idx[idx] = llm

    return [by_idx[i] for i in sorted(by_idx)]

