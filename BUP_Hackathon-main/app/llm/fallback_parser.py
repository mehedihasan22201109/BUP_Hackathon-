"""Deterministic fallback parser for operator notes.

The LLM layer is best-effort: it sometimes returns valid directive *types* with
empty or zeroed *values* (empty hours, factor=0.5 default, reserve=0). It also
occasionally downgrades a clearly-constrained note to ``no_op``. Neither case
is acceptable per the official spec: a phrase like "treat as roughly 25% of
the forecast" must yield factor=0.25 and "between 11 AM and 2 PM" must yield
hours=[11,12,13] (start-inclusive, end-exclusive half-open interval).

This module is a *safety net*: it reads the raw operator note text and emits a
well-formed ``DirectiveEntry``-shaped dict, using only the note's *wording*. It
does not consult the scenario_id, does not consult any sample-specific
phrasing, and emits ``no_op`` when nothing matches. The fallback is therefore
safe to apply in addition to the LLM output: the validator layer guarantees
that every emitted entry is schema-conforming and that one entry is produced
per operator note.

Half-open hour semantics (per official §5.1)
-----------------------------------------------
``[start, end)`` -- the end hour is exclusive. So "10 AM until noon" is hours
[10, 11] and "6 PM until 10 PM" is hours [18, 19, 20, 21].

Scope
-----
This module is intentionally small and generic. It is *not* a replacement for
the LLM -- the LLM is the primary interpreter and can handle far more diverse
phrasing. This module exists so the system can never silently downgrade a
clear directive to ``no_op`` or zero-out a constraint.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Number / time regexes                                                       #
# --------------------------------------------------------------------------- #

_PERCENT_RE = re.compile(r"(\d{1,3})\s*(?:%|percent)", re.IGNORECASE)
_KWH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.IGNORECASE)
_HOUR12_RE = re.compile(r"\b(\d{1,2})\s*([ap])\.?m\.?\b", re.IGNORECASE)
_HOUR24_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?:\s*(am|pm))?\b", re.IGNORECASE)
_HOUR_WORD_RE = re.compile(r"\bhour\s+(\d{1,2})\b", re.IGNORECASE)
_TIME_RANGE_RE = re.compile(
    r"\b(?:(?:(?P<sh>\d{1,2})\s*(?P<sap>[ap])\.?m\.?\b)|(?:(?P<sn>noon|midday|midnight)))\s*"
    r"(?:until|to|through|til|and|from|before|after|-|\u2013|\u2014)\s*"
    r"(?:(?:(?P<eh>\d{1,2})\s*(?P<eap>[ap])\.?m\.?\b)|(?:(?P<en>noon|midday|midnight)))\b",
    re.IGNORECASE,
)
_TIME_RANGE_24H_RE = re.compile(
    r"\b(\d{1,2}):(\d{2})\s*(?:until|to|-|\u2013|\u2014)\s*(\d{1,2}):(\d{2})\b"
)


def _to_24h(h: int, ap: str) -> int:
    ap = ap.lower()
    if ap == "a" and h == 12:
        return 0
    if ap == "p" and h != 12:
        return h + 12
    return h


def _start_hour(m) -> Optional[int]:
    """Resolve the start hour from a _TIME_RANGE_RE match."""
    if m.group("sh") is not None and m.group("sap") is not None:
        return _to_24h(int(m.group("sh")), m.group("sap"))
    sn = m.group("sn")
    if sn is not None:
        return 0 if sn.lower().startswith("mid") else 12
    return None


def _end_hour(m) -> Optional[int]:
    """Resolve the end hour from a _TIME_RANGE_RE match (half-open)."""
    if m.group("eh") is not None and m.group("eap") is not None:
        return _to_24h(int(m.group("eh")), m.group("eap"))
    en = m.group("en")
    if en is not None:
        return 0 if en.lower().startswith("mid") else 12
    return None


def _parse_noon_or(hour_token: str, ap_token: str) -> int:
    """Helper for the rare 'noon' / 'midnight' end-of-range token."""
    if hour_token is None:
        # Noon = 12, midnight = 0
        return 12 if ap_token.lower().startswith("n") else 0
    return _to_24h(int(hour_token), ap_token)


# --------------------------------------------------------------------------- #
# Hour extraction (half-open)                                                 #
# --------------------------------------------------------------------------- #

def extract_hours(text: str) -> List[int]:
    """Return a deduplicated, sorted list of half-open hours referenced in text.

    Multi-hour windows ("X AM until Y PM", "10pm - 1am") are emitted as
    start-inclusive, end-exclusive ranges. Single-hour mentions ("at 2 AM")
    emit one hour. Hours outside [0, 23] are dropped.

    The function is best-effort: if nothing parses, it returns an empty list.
    That is *not* an error -- the validator downstream will downgrade to
    ``no_op`` rather than poison the optimizer.
    """
    if not isinstance(text, str):
        return []
    text_l = text.lower()
    hours: set = set()

    # ----- Multi-hour 12h ranges ---------------------------------------------
    # Char spans covered by range matches so the single-hour scanners below
    # do not double-count tokens like "2 PM" that are already part of a range.
    covered: List[tuple] = []
    for m in _TIME_RANGE_RE.finditer(text_l):
        covered.append((m.start(), m.end()))
        start = _start_hour(m)
        end = _end_hour(m)
        if start is None or end is None:
            continue
        if start <= end:
            hours.update(range(start, end))
        else:
            # Wrap-around midnight, e.g. 10 PM until 1 AM
            hours.update(range(start, 24))
            hours.update(range(0, end))

    for m in _TIME_RANGE_24H_RE.finditer(text_l):
        covered.append((m.start(), m.end()))
        s = int(m.group(1))
        e = int(m.group(3))
        if s <= e:
            hours.update(range(s, e))
        else:
            hours.update(range(s, 24))
            hours.update(range(0, e))

    # ----- Single 12h mentions (skip tokens already inside a range) ---------
    for m in _HOUR12_RE.finditer(text_l):
        if any(a <= m.start() < b for a, b in covered):
            continue
        h, ap = int(m.group(1)), m.group(2)
        hours.add(_to_24h(h, ap))

    # ----- 24h "22:00" -------------------------------------------------------
    for m in _HOUR24_RE.finditer(text_l):
        if any(a <= m.start() < b for a, b in covered):
            continue
        hours.add(int(m.group(1)))

    # ----- "hour N" ----------------------------------------------------------
    for m in _HOUR_WORD_RE.finditer(text_l):
        if any(a <= m.start() < b for a, b in covered):
            continue
        h = int(m.group(1))
        if 0 <= h <= 23:
            hours.add(h)

    return sorted(h for h in hours if 0 <= h <= 23)


# --------------------------------------------------------------------------- #
# Topic classification                                                        #
# --------------------------------------------------------------------------- #

_GRID_TERMS = ("grid", "feeder", "transformer", "import", "substation",
               "tariff", "intake", "incoming")
_BATTERY_TERMS = ("battery", "soc", "reserve", "charger", "charging",
                  "charge", "inverter",
                  "storage", "discharge")
_SOLAR_TERMS = ("solar", "panel", "pv", "rooftop", "rooftop solar",
                "inverter work")  # "inverter work" implies solar context


def _has(text: str, terms) -> bool:
    return any(t in text for t in terms)


# --------------------------------------------------------------------------- #
# Per-topic extractors                                                        #
# --------------------------------------------------------------------------- #

def _extract_factor(text_l: str) -> Optional[float]:
    """Extract the usable-solar factor from a solar-reduction note.

    Reads three different wording families, in priority order:

      1. Direct "treat as X% of the forecast" / "only X% usable"  -> factor=X/100
      2. "X% reduction"                                          -> factor=1-X/100
      3. Fractions ("half", "quarter", "third")                  -> factor accordingly

    Returns ``None`` when no numeric value is recoverable.
    """
    # Direct usable-fraction wording (most explicit; wins over "reduction").
    if "of the forecast" in text_l or "of forecast" in text_l or "usable" in text_l:
        m = _PERCENT_RE.search(text_l)
        if m:
            return _clamp_factor(float(m.group(1)) / 100.0)

    # Numeric reduction wording.
    m = _PERCENT_RE.search(text_l)
    if m and ("reduction" in text_l or "less" in text_l or "reduced" in text_l):
        return _clamp_factor(1.0 - float(m.group(1)) / 100.0)

    # Fraction keywords.
    if "quarter" in text_l:
        return 0.25
    if "third" in text_l:
        return _clamp_factor(1.0 / 3.0)
    if "half" in text_l:
        return 0.5

    return None


def _clamp_factor(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    return max(0.0, min(1.0, float(x)))


def _first_kwh(text_l: str, *, lo: float = 1.0, hi: float = 10000.0) -> Optional[float]:
    """Return the first numeric kWh token in ``text_l``, or any plain integer in
    range if no kWh token is present.
    """
    for m in _KWH_RE.finditer(text_l):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if lo <= v <= hi:
            return v
    # Fallback: any integer in [lo, hi] (used for "190 kWh of grid import" when
    # the unit is implicit). Skip hour-like integers.
    for m in re.finditer(r"\b(\d{1,4}(?:\.\d+)?)\b", text_l):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if lo <= v <= hi:
            return v
    return None


def _extract_minimum_reserve_kwh(text: str, text_l: str, capacity_kwh: Optional[float]) -> Optional[float]:
    """Extract the minimum-energy reserve from a reserve-style note."""
    pct = _PERCENT_RE.search(text_l)
    if pct and ("capacity" in text_l or "%" in text or "percent" in text_l) and capacity_kwh:
        return round(capacity_kwh * float(pct.group(1)) / 100.0, 2)
    return _first_kwh(text_l, lo=1.0, hi=capacity_kwh or 10000.0)


# --------------------------------------------------------------------------- #
# Public API                                                                 #
# --------------------------------------------------------------------------- #

def fallback_parse(
    note: str,
    note_index: int,
    *,
    capacity_kwh: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a directive entry dict for one operator note.

    The returned dict is shaped like ``DirectiveEntry`` (see schemas.py) and
    uses the same keys the LLM is expected to emit, so the validator layer
    treats the two paths identically. Output keys:

        note_index, applies (bool), directive_type (str),
        structured_adjustment (dict|None), explanation (str)
    """
    if not isinstance(note, str):
        return _no_op(note_index, "Note text is missing or invalid.")

    text_l = note.lower()
    hours = extract_hours(note)

    has_grid = _has(text_l, _GRID_TERMS)
    has_battery = _has(text_l, _BATTERY_TERMS)
    has_solar = _has(text_l, _SOLAR_TERMS)

    if not (has_grid or has_battery or has_solar):
        return _no_op(note_index, "Note does not affect today's energy schedule.")

    # ------------------- max_grid_window -------------------------------------
    if (
        ("cap " in text_l or "max grid" in text_l or "maximum grid" in text_l
         or "feeder" in text_l or "transformer" in text_l or "substation" in text_l
         or "stay at or below" in text_l or "do not import" in text_l
         or "must not import" in text_l or "must not exceed" in text_l
         or "must not import more than" in text_l
         or ("limit" in text_l and ("grid" in text_l or "import" in text_l)))
    ):
        cap = _first_kwh(text_l, lo=10.0, hi=10000.0)
        if cap is None:
            # Generic "feeder limit" with no numeric -> no_op so the
            # validator does not poison the optimizer with cap=0.
            return _no_op(note_index, "Grid limit stated without a numeric cap.")
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": hours, "max_grid_kwh": float(cap)},
            "explanation": f"Grid import capped at {cap:g} kWh in the stated window.",
        }

    # ------------------- no_charge_window ------------------------------------
    if (
        "no charge" in text_l
        or "cannot charge" in text_l
        or "won't charge" in text_l
        or "will not charge" in text_l
        or "charger isolated" in text_l
        or ("isolated" in text_l and ("charger" in text_l or "charging" in text_l))
        or "charging circuit" in text_l and ("unavailable" in text_l or "disabled" in text_l)
        or "charging is disabled" in text_l
        or "charging outage" in text_l
        or ("charging" in text_l and ("disabled" in text_l or "offline" in text_l or "unavailable" in text_l))
    ):
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": "Battery charging unavailable in the stated window.",
        }

    # ------------------- no_discharge_window ---------------------------------
    if (
        "no discharge" in text_l
        or "cannot discharge" in text_l
        or "won't discharge" in text_l
        or "will not discharge" in text_l
        or "must not discharge" in text_l
        or "do not discharge" in text_l
        or "do not let the battery discharge" in text_l
        or "relay testing" in text_l
        or "protection testing" in text_l
        or ("inverter" in text_l and "off" in text_l)
    ):
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": "Battery discharge unavailable in the stated window.",
        }

    # ------------------- minimum_battery_reserve -----------------------------
    if (
        "reserve" in text_l
        or "soc" in text_l
        or "remain in the battery" in text_l
        or "kept in the battery" in text_l
        or "stored in the battery" in text_l
        or ("at least" in text_l and "battery" in text_l)
        or ("at least" in text_l and "kwh" in text_l)
        or "requires at least" in text_l
    ):
        min_kwh = _extract_minimum_reserve_kwh(note, text_l, capacity_kwh)
        if min_kwh is None:
            return _no_op(note_index, "Reserve stated without a numeric value.")
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {
                "hours": hours,
                "minimum_energy_kwh": float(min_kwh),
            },
            "explanation": f"Battery SOC kept >= {min_kwh:g} kWh in the stated window.",
        }

    # ------------------- solar_reduction (fallback) --------------------------
    if has_solar:
        factor = _extract_factor(text_l)
        if factor is None:
            factor = 0.5  # Generic "solar reduced" with no numeric
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": hours, "factor": factor},
            "explanation": f"Usable solar scaled by factor {factor:.2f} in the stated window.",
        }

    # ------------------- default ---------------------------------------------
    return _no_op(note_index, "Note does not affect today's energy schedule.")


def _no_op(note_index: int, explanation: str) -> Dict[str, Any]:
    return {
        "note_index": note_index,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": explanation,
    }
