"""Deterministic validation of LLM-emitted directives.

Why this exists
---------------
Even with strict prompts, LLMs can:

  * emit a directive_type outside the allowed enum
  * produce hours outside [0, 23], with duplicates, or unsorted
  * quote a factor outside [0, 1]
  * pick a reserve outside the battery envelope
  * quote a max_grid that is negative
  * forget the structured_adjustment for an applicable directive
  * emit prose-only content with no JSON

We cannot let any of these poison the optimizer. The validator:

  1. Coerces entries to the documented shape.
  2. Replaces out-of-range values with safe defaults.
  3. Downgrades inapplicable / malformed entries to ``no_op``.
  4. Guarantees exactly one output entry per input note, in order.

The optimizer is therefore never asked to trust anything the LLM said.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from ..schemas import DirectiveType

logger = logging.getLogger(__name__)


ALLOWED_DIRECTIVE_TYPES: Set[str] = {dt.value for dt in DirectiveType}


# --------------------------------------------------------------------------- #
# Building blocks                                                             #
# --------------------------------------------------------------------------- #

def _sanitize_hours(raw: Any) -> Optional[List[int]]:
    """Return a sorted, deduped, ascending list of ints in [0, 23] or None."""
    if not isinstance(raw, list):
        return None
    out: List[int] = []
    seen: Set[int] = set()
    for v in raw:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if 0 <= iv <= 23 and iv not in seen:
            seen.add(iv)
            out.append(iv)
    out.sort()
    return out


def _clamp_factor(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN guard
        return None
    return max(0.0, min(1.0, f))


def _nonneg(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v or v < 0:
        return None
    return v


# --------------------------------------------------------------------------- #
# Per-directive normalization                                                #
# --------------------------------------------------------------------------- #

def _normalize_solar_reduction(adj: Any) -> Dict[str, Any]:
    hours = _sanitize_hours((adj or {}).get("hours")) or []
    factor = _clamp_factor((adj or {}).get("factor"))
    if factor is None:
        factor = 0.0
    return {"hours": hours, "factor": factor}


def _normalize_reserve(adj: Any, *, capacity_kwh: float, initial_energy_kwh: float, minimum_energy_kwh: float) -> Dict[str, Any]:
    hours = _sanitize_hours((adj or {}).get("hours")) or []
    requested = _nonneg((adj or {}).get("minimum_energy_kwh"))
    # Clamp the requested reserve into the legal [minimum_energy_kwh, capacity_kwh] band.
    if requested is None:
        # Default to the configured minimum if the LLM omitted it.
        minimum = minimum_energy_kwh
    else:
        minimum = max(minimum_energy_kwh, min(capacity_kwh, requested))
    # Final SOC cannot exceed capacity. The reserve is only useful up to capacity.
    minimum = min(minimum, capacity_kwh)
    minimum = max(minimum, minimum_energy_kwh)
    return {"hours": hours, "minimum_energy_kwh": float(minimum)}


def _normalize_no_charge(adj: Any) -> Dict[str, Any]:
    return {"hours": _sanitize_hours((adj or {}).get("hours")) or []}


def _normalize_no_discharge(adj: Any) -> Dict[str, Any]:
    return {"hours": _sanitize_hours((adj or {}).get("hours")) or []}


def _normalize_max_grid(adj: Any) -> Dict[str, Any]:
    hours = _sanitize_hours((adj or {}).get("hours")) or []
    cap = _nonneg((adj or {}).get("max_grid_kwh"))
    if cap is None:
        cap = 0.0
    return {"hours": hours, "max_grid_kwh": float(cap)}


# --------------------------------------------------------------------------- #
# Public API                                                                 #
# --------------------------------------------------------------------------- #

def normalize_entry(
    note_index: int,
    raw_entry: Optional[Dict[str, Any]],
    *,
    battery: Optional[Any] = None,
) -> Dict[str, Any]:
    """Normalize one LLM-emitted entry into a safe, schema-conforming dict.

    ``battery`` is required only for ``minimum_battery_reserve`` clamping;
    if it is missing, the reserve is clamped to ``[0, +inf)``.
    """
    base_explanation = (
        "Operator note has no impact on today's energy schedule."
    )
    if not isinstance(raw_entry, dict):
        return {
            "note_index": note_index,
            "applies": False,
            "directive_type": DirectiveType.NO_OP.value,
            "structured_adjustment": None,
            "explanation": base_explanation,
        }

    dtype = raw_entry.get("directive_type")
    if dtype not in ALLOWED_DIRECTIVE_TYPES:
        dtype = DirectiveType.NO_OP.value

    applies_raw = raw_entry.get("applies", True)
    applies = bool(applies_raw) and dtype != DirectiveType.NO_OP.value

    adj = raw_entry.get("structured_adjustment")
    explanation = raw_entry.get("explanation") or ""

    # no_op: force applies=False and structured_adjustment=None
    if dtype == DirectiveType.NO_OP.value:
        return {
            "note_index": note_index,
            "applies": False,
            "directive_type": DirectiveType.NO_OP.value,
            "structured_adjustment": None,
            "explanation": str(explanation).strip() or base_explanation,
        }

    if not isinstance(adj, dict):
        adj = {}

    if dtype == DirectiveType.SOLAR_REDUCTION.value:
        sa = _normalize_solar_reduction(adj)
    elif dtype == DirectiveType.MINIMUM_BATTERY_RESERVE.value:
        cap = getattr(battery, "capacity_kwh", None) or 0.0
        init = getattr(battery, "initial_energy_kwh", None) or 0.0
        minimum = getattr(battery, "minimum_energy_kwh", None) or 0.0
        sa = _normalize_reserve(
            adj,
            capacity_kwh=cap,
            initial_energy_kwh=init,
            minimum_energy_kwh=minimum,
        )
    elif dtype == DirectiveType.NO_CHARGE_WINDOW.value:
        sa = _normalize_no_charge(adj)
    elif dtype == DirectiveType.NO_DISCHARGE_WINDOW.value:
        sa = _normalize_no_discharge(adj)
    elif dtype == DirectiveType.MAX_GRID_WINDOW.value:
        sa = _normalize_max_grid(adj)
    else:  # pragma: no cover -- exhaustive due to ALLOWED_DIRECTIVE_TYPES guard
        return {
            "note_index": note_index,
            "applies": False,
            "directive_type": DirectiveType.NO_OP.value,
            "structured_adjustment": None,
            "explanation": base_explanation,
        }

    return {
        "note_index": note_index,
        "applies": applies,
        "directive_type": dtype,
        "structured_adjustment": sa,
        "explanation": str(explanation).strip() or "Operator directive applied to today's energy schedule.",
    }


def normalize_entries(
    raw_entries: List[Any],
    operator_notes: List[str],
    *,
    battery: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Normalize the full interpretation list, preserving note order.

    Guarantees ``len(output) == len(operator_notes)`` and that each
    ``note_index`` matches its position.
    """
    out: List[Dict[str, Any]] = []
    # Index LLM output by note_index for stable matching
    by_idx: Dict[int, Any] = {}
    for entry in raw_entries or []:
        if isinstance(entry, dict):
            try:
                ni = int(entry.get("note_index", -1))
            except (TypeError, ValueError):
                continue
            if ni not in by_idx:
                by_idx[ni] = entry

    for idx, _note in enumerate(operator_notes):
        out.append(normalize_entry(idx, by_idx.get(idx), battery=battery))
    return out
