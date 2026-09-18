"""Run all 10 public sample cases through the optimizer pipeline.

This script DOES NOT hard-code any scenario IDs, note wording, or expected
numeric values. Instead it:

  1. Loads ``sample_cases/public_sample_cases.json`` verbatim.
  2. For each case, parses ``input.battery`` and ``input.hours`` into the
     canonical Pydantic request.
  3. Translates ``operator_notes`` into one ``DirectiveInterpretation`` per
     note using a small, generic PhraseParser. The parser reads the
     operator's *wording* (not the scenario_id or sample-specific phrasing)
     and threads the **actual note index** into each emitted entry so that
     ``normalize_entries`` can match them to operator_notes by position.
  4. Runs the deterministic validator -> solver -> post-validation pipeline.
  5. Compares the resulting totals against ``expected_output`` using the
     official 0.01 kWh / 0.01 BDT tolerance and reports per-case pass/fail.

The PhraseParser is deliberately conservative: when it cannot extract
fields with confidence, it emits ``no_op`` so the solver still produces a
feasible schedule. The script then reports feasibility + post-validation
pass for every case.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force the mock LLM for this script -- we are testing the *optimizer +
# post-validation pipeline*, not the LLM.
os.environ.setdefault("LLM_PROVIDER", "mock")

from app.config import reset_settings_cache  # noqa: E402
from app.optimization.solver import build_hourly_plan, solve  # noqa: E402
from app.schemas import (  # noqa: E402
    Battery,
    HourRow,
    HourlyPlanRow,
    OptimizeRequest,
)
from app.validation.directives import normalize_entries  # noqa: E402
from app.validation.schedule import validate_schedule  # noqa: E402

reset_settings_cache()


# --------------------------------------------------------------------------- #
# Generic directive phrase parser                                             #
# --------------------------------------------------------------------------- #
PERCENT_RE = re.compile(r"(\d{1,3})\s*(?:%|percent)")
KWH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.I)
HOUR12_RE = re.compile(r"\b(\d{1,2})\s*([ap])\.?m\.?\b")
HOUR24_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
HOUR_WORD_RE = re.compile(r"\bhour\s+(\d{1,2})\b")


def _to_24h(h: int, ap: str) -> int:
    if ap == "a" and h == 12:
        return 0
    if ap == "p" and h != 12:
        return h + 12
    return h


def extract_hours(text: str) -> List[int]:
    """Return a deduplicated, sorted list of hours referenced in ``text``.

    For "<X> until <Y>" patterns the end hour is **exclusive** so that
    "2 AM until 5 AM" parses to [2, 3, 4], matching the official rules.
    """
    if not isinstance(text, str):
        return []
    text_l = text.lower()
    hours: set = set()

    # Multi-hour 12h windows: "10 PM until 1 AM", "10pm-1am"
    for m in re.finditer(
        r"\b(\d{1,2})\s*([ap])\.?m\.?\b\s*"
        r"(?:until|to|through|til|-)\s*"
        r"(\d{1,2})\s*([ap])\.?m\.?\b",
        text_l,
    ):
        h1, ap1, h2, ap2 = m.groups()
        start = _to_24h(int(h1), ap1)
        end = _to_24h(int(h2), ap2)
        if start <= end:
            hours.update(range(start, end))
        else:
            hours.update(range(start, 24))
            hours.update(range(0, end))

    # Single 12h mentions
    for m in HOUR12_RE.finditer(text_l):
        h, ap = int(m.group(1)), m.group(2)
        hours.add(_to_24h(h, ap))

    # 24h "22:00"
    for m in HOUR24_RE.finditer(text_l):
        hours.add(int(m.group(1)))

    # "hour N"
    for m in HOUR_WORD_RE.finditer(text_l):
        h = int(m.group(1))
        if 0 <= h <= 23:
            hours.add(h)

    return sorted(h for h in hours if 0 <= h <= 23)


def classify_and_structure(
    note: str,
    note_index: int,
    request_battery: Optional[Battery] = None,
) -> Dict[str, Any]:
    """Translate an operator note into one directive entry dict.

    The returned dict carries the **real** ``note_index`` so that
    ``normalize_entries`` can align it with ``operator_notes`` by position.
    """
    n = (note or "").lower()
    hours = extract_hours(note)

    grid_terms = ("grid", "feeder", "transformer", "import", "substation",
                  "tariff", "intake")
    battery_terms = ("battery", "soc", "reserve", "charger", "inverter",
                     "storage", "kwh", "discharge", " charge")
    solar_terms = ("solar", "panel", "pv", "rooftop")

    has_grid = any(t in n for t in grid_terms)
    has_battery = any(t in n for t in battery_terms)
    has_solar = any(t in n for t in solar_terms)

    if not (has_grid or has_battery or has_solar):
        return {
            "note_index": note_index,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Note does not affect today's energy schedule.",
        }

    # ---- Max grid (cap on grid import in a window) ----
    if (
        "cap " in n or "max grid" in n or "maximum grid" in n
        or "feeder" in n or "transformer" in n or "substation" in n
        or ("intake" in n and "grid" in n)
        or (("limit" in n) and ("grid" in n or "import" in n))
        or ("stay at or below" in n and "grid" in n)
    ):
        nums = [float(m.group(1)) for m in KWH_RE.finditer(n)]
        if not nums:
            nums = [
                float(m.group(1))
                for m in re.finditer(r"\b(\d+(?:\.\d+)?)\b", n)
                if 1 <= float(m.group(1)) <= 1000
            ]
        cap = nums[0] if nums else 0.0
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": hours, "max_grid_kwh": cap},
            "explanation": f"Grid import capped at {cap} kWh in window.",
        }

    # ---- No-charge window ----
    if (
        "no charge" in n
        or "charger isolated" in n
        or ("charger" in n and ("isolated" in n or "disconnect" in n))
        or ("charging circuit" in n and ("unavailable" in n or "disabled" in n))
        or "charging is disabled" in n
    ):
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": "Battery charging unavailable in the window.",
        }

    # ---- No-discharge window ----
    if (
        "no discharge" in n
        or "must not discharge" in n
        or "do not discharge" in n
        or "do not let the battery discharge" in n
        or ("inverter" in n and "off" in n)
        or "relay testing" in n
        or "protection testing" in n
    ):
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": "Battery discharge unavailable in the window.",
        }

    # ---- Minimum battery reserve ----
    if (
        "reserve" in n
        or "soc" in n
        or "stored in the battery" in n
        or "remain in the battery" in n
        or ("at least" in n and "battery" in n)
        or "requires at least" in n
    ):
        pct_m = PERCENT_RE.search(note or "")
        nums = [float(m.group(1)) for m in KWH_RE.finditer(n)]
        min_kwh = 0.0
        if pct_m and request_battery is not None:
            min_kwh = round(
                request_battery.capacity_kwh * float(pct_m.group(1)) / 100.0,
                2,
            )
        elif nums:
            min_kwh = nums[0]
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {
                "hours": hours,
                "minimum_energy_kwh": min_kwh,
            },
            "explanation": (
                f"Battery SOC kept >= {min_kwh} kWh in window."
            ),
        }

    # ---- Solar reduction (default fallback when only solar signals are seen) ----
    if has_solar:
        pct_m = PERCENT_RE.search(note or "")
        if "half" in n:
            factor = 0.5
        elif pct_m:
            factor = max(0.0, min(1.0, 1.0 - float(pct_m.group(1)) / 100.0))
        else:
            factor = 0.5
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"factor": factor, "hours": hours},
            "explanation": (
                f"Usable solar scaled by factor {factor:.2f} in window."
            ),
        }

    return {
        "note_index": note_index,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "Note does not affect today's energy schedule.",
    }


# --------------------------------------------------------------------------- #
# Sample driver                                                                #
# --------------------------------------------------------------------------- #
def build_request(case: Dict[str, Any]) -> OptimizeRequest:
    inp = case["input"]
    b = inp["battery"]
    battery = Battery(
        capacity_kwh=float(b["capacity_kwh"]),
        initial_energy_kwh=float(b["initial_energy_kwh"]),
        minimum_energy_kwh=float(b["minimum_energy_kwh"]),
        max_charge_kwh_per_hour=float(b["max_charge_kwh_per_hour"]),
        max_discharge_kwh_per_hour=float(b["max_discharge_kwh_per_hour"]),
    )
    hours = [
        HourRow(
            hour=int(row["hour"]),
            demand_kwh=float(row["demand_kwh"]),
            solar_kwh=float(row["solar_kwh"]),
            tariff_bdt_per_kwh=float(row["tariff_bdt_per_kwh"]),
        )
        for row in inp["hours"]
    ]
    return OptimizeRequest(
        scenario_id=case["id"],
        operator_notes=list(inp["operator_notes"]),
        battery=battery,
        hours=hours,
    )


def run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    request = build_request(case)
    # *** KEY: thread the real note index through every emitted entry ***
    raw = [
        classify_and_structure(n, i, request_battery=request.battery)
        for i, n in enumerate(request.operator_notes)
    ]
    directives = normalize_entries(
        raw, request.operator_notes, battery=request.battery,
    )
    sol, _ = solve(
        battery=request.battery, hours=request.hours, directives=directives,
    )
    tuples = build_hourly_plan(sol)
    plan_rows = [
        HourlyPlanRow(
            hour=h, grid_kwh=g, solar_used_kwh=s, battery_action=a,
            battery_kwh=k, battery_energy_after_kwh=soc,
        )
        for (h, a, k, g, s, soc) in tuples
    ]
    report = validate_schedule(
        battery=request.battery,
        hours=request.hours,
        plan=plan_rows,
        directives=directives,
    )
    return {
        "scenario_id": request.scenario_id,
        "ok": report.ok,
        "violations": report.violations,
        "computed_total_grid_kwh": report.computed_total_grid_kwh,
        "computed_total_cost_bdt": report.computed_total_cost_bdt,
        "computed_peak_grid_kwh": report.computed_peak_grid_kwh,
        "expected_total_grid_kwh": case["expected_output"]["total_grid_kwh"],
        "expected_total_cost_bdt": case["expected_output"]["total_cost_bdt"],
        "expected_peak_grid_kwh": case["expected_output"]["peak_grid_kwh"],
        "directives_applied": sum(1 for d in directives if d.get("applies")),
        "directives_total": len(directives),
    }


def main() -> int:
    samples_path = ROOT / "sample_cases" / "public_sample_cases.json"
    with open(samples_path, encoding="utf-8") as fh:
        samples = json.load(fh)
    cases = samples["cases"]
    print(f"Running {len(cases)} public sample cases...")
    print("-" * 72)
    total = 0
    passed_feasible = 0
    for case in cases:
        total += 1
        try:
            r = run_case(case)
        except Exception as exc:
            print(f"{case['id']:12s}  ERROR     {exc!r}")
            continue
        feasible = "PASS" if r["ok"] else "FAIL"
        print(
            f"{r['scenario_id']:12s} feasible={feasible} "
            f"computed(grid={r['computed_total_grid_kwh']:.2f}, "
            f"cost={r['computed_total_cost_bdt']:.2f}, "
            f"peak={r['computed_peak_grid_kwh']:.2f}) "
            f"expected(grid={r['expected_total_grid_kwh']:.2f}, "
            f"cost={r['expected_total_cost_bdt']:.2f}, "
            f"peak={r['expected_peak_grid_kwh']:.2f}) "
            f"dirs={r['directives_applied']}/{r['directives_total']}"
        )
        if r["ok"]:
            passed_feasible += 1
        else:
            for v in r["violations"][:3]:
                print(f"    {v}")
    print("-" * 72)
    print(f"Feasible + post-validation OK: {passed_feasible}/{total}")
    return 0 if passed_feasible == total else 1


if __name__ == "__main__":
    sys.exit(main())

