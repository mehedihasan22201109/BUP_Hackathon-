"""Helper that converts validated directives into per-hour state.

This is the small adapter between the validated directive list (output of
``app.validation.directives.normalize_entries``) and the LP model. Keeping
it in its own module avoids a circular import between model and directives.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from ..schemas import DirectiveType


class DirectiveState:
    """Per-hour state derived from a list of normalized directive dicts.

    The class is a thin façade over Python sets/dicts so the LP model can
    query membership in O(1).
    """

    def __init__(self, directives: List[dict], battery) -> None:
        self._battery = battery
        self.no_charge_hours: Set[int] = set()
        self.no_discharge_hours: Set[int] = set()
        self.max_grid_hours: Set[int] = set()
        self.max_grid_caps: Dict[int, float] = {}
        self._solar_factor: Dict[int, float] = {}
        self._reserve_floor_hour: Dict[int, float] = {}

        # Default floor is the battery minimum_energy_kwh everywhere; the
        # minimum_battery_reserve directive overrides it on its hours.
        self._base_floor = getattr(battery, "minimum_energy_kwh", 0.0)

        for d in directives:
            if not d.get("applies"):
                continue
            dtype = d.get("directive_type")
            adj = d.get("structured_adjustment") or {}
            if dtype == DirectiveType.NO_CHARGE_WINDOW.value:
                self.no_charge_hours.update(int(x) for x in adj.get("hours", []))
            elif dtype == DirectiveType.NO_DISCHARGE_WINDOW.value:
                self.no_discharge_hours.update(int(x) for x in adj.get("hours", []))
            elif dtype == DirectiveType.MAX_GRID_WINDOW.value:
                hours = [int(x) for x in adj.get("hours", [])]
                cap = float(adj.get("max_grid_kwh", 0.0) or 0.0)
                for h in hours:
                    self.max_grid_hours.add(h)
                    self.max_grid_caps[h] = cap
            elif dtype == DirectiveType.SOLAR_REDUCTION.value:
                factor = float(adj.get("factor", 1.0) or 1.0)
                for h in adj.get("hours", []):
                    self._solar_factor[int(h)] = factor
            elif dtype == DirectiveType.MINIMUM_BATTERY_RESERVE.value:
                target = float(adj.get("minimum_energy_kwh", self._base_floor))
                for h in adj.get("hours", []):
                    self._reserve_floor_hour[int(h)] = target

    # ---- Query API used by the LP model ----
    def solar_factor(self, hour: int) -> float:
        return self._solar_factor.get(hour, 1.0)

    def reserve_floor(self, hour: int) -> float:
        if hour in self._reserve_floor_hour:
            return max(self._base_floor, self._reserve_floor_hour[hour])
        return self._base_floor

    def max_grid_for(self, hour: int) -> Optional[float]:
        return self.max_grid_caps.get(hour)
