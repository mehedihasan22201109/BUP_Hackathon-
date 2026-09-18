"""Pydantic schemas for the GridWise HTTP API.

Field names and types mirror the official Problem Statement v2.0 and the
``BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`` pack exactly.

The strict validation here is what produces HTTP 422 automatically when
clients send malformed payloads (Pydantic surfaces its own errors as 422 by
default in FastAPI).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #

class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class BatteryAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


# --------------------------------------------------------------------------- #
# Request                                                                     #
# --------------------------------------------------------------------------- #

class Battery(BaseModel):
    """Battery operating envelope."""

    model_config = ConfigDict(extra="forbid")

    capacity_kwh: float = Field(..., gt=0)
    initial_energy_kwh: float = Field(..., ge=0)
    minimum_energy_kwh: float = Field(..., ge=0)
    max_charge_kwh_per_hour: float = Field(..., ge=0)
    max_discharge_kwh_per_hour: float = Field(..., ge=0)

    @model_validator(mode="after")
    def _check_envelope(self) -> "Battery":
        if self.initial_energy_kwh > self.capacity_kwh + 1e-9:
            raise ValueError(
                "initial_energy_kwh must be <= capacity_kwh"
            )
        if self.minimum_energy_kwh > self.capacity_kwh + 1e-9:
            raise ValueError(
                "minimum_energy_kwh must be <= capacity_kwh"
            )
        if self.minimum_energy_kwh > self.initial_energy_kwh + 1e-9:
            # A schedule can still be feasible if we charge before the
            # reserve window; we keep this strict so callers fix bad inputs.
            raise ValueError(
                "minimum_energy_kwh must be <= initial_energy_kwh to keep "
                "hour 0 feasible without violating the reserve"
            )
        return self


class HourRow(BaseModel):
    """One hour of the 24-hour horizon."""

    model_config = ConfigDict(extra="forbid")

    hour: int = Field(..., ge=0, le=23)
    demand_kwh: float = Field(..., ge=0)
    solar_kwh: float = Field(..., ge=0)
    tariff_bdt_per_kwh: float = Field(..., ge=0)


class OptimizeRequest(BaseModel):
    """POST /optimize-energy request body."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., min_length=1)
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1 to 3 operator notes per official spec section 7.1")
    battery: Battery
    hours: List[HourRow]

    @model_validator(mode="after")
    def _check_hours(self) -> "OptimizeRequest":
        if len(self.hours) != 24:
            raise ValueError("hours must contain exactly 24 entries")
        seen = []
        for row in self.hours:
            if row.hour in seen:
                raise ValueError(f"duplicate hour {row.hour} in hours[]")
            seen.append(row.hour)
        if sorted(seen) != list(range(24)):
            raise ValueError("hours[] must contain each integer 0..23 exactly once")
        return self


# --------------------------------------------------------------------------- #
# Response                                                                    #
# --------------------------------------------------------------------------- #

class StructuredAdjustment(BaseModel):
    """The directive-specific payload. ``None`` for ``no_op``."""

    model_config = ConfigDict(extra="forbid")

    hours: Optional[List[int]] = Field(default=None)
    factor: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    minimum_energy_kwh: Optional[float] = Field(default=None, ge=0.0)
    max_grid_kwh: Optional[float] = Field(default=None, ge=0.0)


class DirectiveInterpretation(BaseModel):
    """One entry per operator note, in ``note_index`` order."""

    model_config = ConfigDict(extra="forbid")

    note_index: int = Field(..., ge=0)
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[StructuredAdjustment] = Field(default=None)
    explanation: str = Field(..., min_length=1)


class HourlyPlanRow(BaseModel):
    """One hour of the optimized plan."""

    model_config = ConfigDict(extra="forbid")

    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: BatteryAction
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float = Field(..., ge=0)


class OptimizeResponse(BaseModel):
    """POST /optimize-energy response body."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanRow]
    total_grid_kwh: float = Field(..., ge=0)
    total_cost_bdt: float = Field(..., ge=0)
    peak_grid_kwh: float = Field(..., ge=0)
    plan_summary: str = Field(..., min_length=1)


class HealthResponse(BaseModel):
    """GET /health response body."""

    status: Literal["ok"] = "ok"
    service: Literal["gridwise-llm-energy-optimizer"] = "gridwise-llm-energy-optimizer"
    version: str = "1.0.0"


# --------------------------------------------------------------------------- #
# Internal: normalized optimizer result (used between modules)                #
# --------------------------------------------------------------------------- #

class OptimizerSolution(BaseModel):
    """Result of the LP solver, before response assembly."""

    model_config = ConfigDict(extra="forbid")

    grid: Dict[int, float]
    solar_used: Dict[int, float]
    battery_charge: Dict[int, float]
    battery_discharge: Dict[int, float]
    battery_energy_after: Dict[int, float]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
