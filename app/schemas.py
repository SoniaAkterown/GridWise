from typing import List, Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# ==========================================
# Input Schemas
# ==========================================

class HourInput(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Unique integer from 0 to 23.")
    demand_kwh: float = Field(..., ge=0, description="Campus demand that must be supplied in this hour.")
    solar_kwh: float = Field(..., ge=0, description="Base solar energy available before adjustments.")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Grid electricity price for this hour.")


class BatteryInput(BaseModel):
    capacity_kwh: float = Field(..., gt=0, description="Maximum energy the battery can store.")
    initial_energy_kwh: float = Field(..., ge=0, description="Battery energy at start of hour 0.")
    minimum_energy_kwh: float = Field(..., ge=0, description="Base reserve level battery must not go below.")
    max_charge_kwh_per_hour: float = Field(..., gt=0, description="Maximum energy added in one hour.")
    max_discharge_kwh_per_hour: float = Field(..., gt=0, description="Maximum energy removed in one hour.")


class EnergyRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1, description="Unique synthetic scenario identifier.")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1 to 3 operator notes.")
    hours: List[HourInput] = Field(..., min_length=24, max_length=24, description="Exactly 24 hourly entries.")
    battery: BatteryInput

    @field_validator("hours")
    @classmethod
    def validate_hours_sequence(cls, v: List[HourInput]) -> List[HourInput]:
        if len(v) != 24:
            raise ValueError("hours array must contain exactly 24 entries.")
        seen_hours = set()
        for idx, item in enumerate(v):
            if item.hour in seen_hours:
                raise ValueError(f"Duplicate hour {item.hour} found in hours array.")
            seen_hours.add(item.hour)
            if item.hour != idx:
                # Warning or reorder, but check 0..23 exist
                pass
        if seen_hours != set(range(24)):
            raise ValueError("hours array must contain unique integers 0 through 23.")
        return sorted(v, key=lambda x: x.hour)


# ==========================================
# Directive Schemas
# ==========================================

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
]

class SolarReductionAdjustment(BaseModel):
    hours: List[int]
    factor: float


class MinReserveAdjustment(BaseModel):
    hours: List[int]
    minimum_energy_kwh: float


class WindowAdjustment(BaseModel):
    hours: List[int]


class MaxGridAdjustment(BaseModel):
    hours: List[int]
    max_grid_kwh: float


StructuredAdjustmentType = Optional[
    Union[
        SolarReductionAdjustment,
        MinReserveAdjustment,
        MaxGridAdjustment,
        WindowAdjustment
    ]
]

class DirectiveInterpretationItem(BaseModel):
    note_index: int = Field(..., ge=0)
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[Union[dict, StructuredAdjustmentType]] = None
    explanation: str

    @model_validator(mode="after")
    def validate_applies_consistency(self):
        if self.directive_type == "no_op":
            if self.applies:
                raise ValueError("applies must be false for directive_type no_op")
            if self.structured_adjustment is not None:
                raise ValueError("structured_adjustment must be null for no_op")
        else:
            if not self.applies:
                raise ValueError(f"applies must be true for directive_type {self.directive_type}")
            if self.structured_adjustment is None:
                raise ValueError(f"structured_adjustment cannot be null for {self.directive_type}")
        return self


# ==========================================
# Hourly Plan & Response Schemas
# ==========================================

BatteryActionType = Literal["charge", "discharge", "idle"]

class HourlyPlanItem(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: BatteryActionType
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float = Field(..., ge=0)


class EnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretationItem]
    hourly_plan: List[HourlyPlanItem] = Field(..., min_length=24, max_length=24)
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class QuickSolveRequest(BaseModel):
    request: EnergyRequest
    directives: List[DirectiveInterpretationItem]

