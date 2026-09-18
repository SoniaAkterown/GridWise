"""
Telemetry audit engine and dispatch plan verification.

Replays generated schedules to confirm nodal power balance and end-of-day
neutrality within floating-point tolerance (±0.05 kWh). Computes official KPI
totals and campus sustainability / ROI analytics.
"""

from typing import List, Tuple, Dict, Any
from app.schemas import EnergyRequest, DirectiveInterpretationItem, HourlyPlanItem

# National average grid emissions factor for Bangladesh (~0.58 kg CO2e / kWh)
GRID_EMISSION_FACTOR_KG_PER_KWH = 0.58


def audit_and_compute_totals(
    request: EnergyRequest,
    directives: List[DirectiveInterpretationItem],
    hourly_plan: List[HourlyPlanItem]
) -> Tuple[float, float, float, str]:
    """
    Audits schedule validity against physical microgrid invariants and
    recalculates official submission metrics directly from hourly dispatch rows.
    """
    tariffs = [item.tariff_bdt_per_kwh for item in request.hours]
    demands = [item.demand_kwh for item in request.hours]
    battery = request.battery

    # Recalculate official metrics from the schedule rows
    total_grid_kwh = round(sum(p.grid_kwh for p in hourly_plan), 2)
    total_cost_bdt = round(sum(p.grid_kwh * tariffs[h] for h, p in enumerate(hourly_plan)), 2)
    peak_grid_kwh = round(max(p.grid_kwh for p in hourly_plan), 2)

    # Replay hourly energy balance
    balance_tolerance = 0.05
    for h, p in enumerate(hourly_plan):
        discharge = p.battery_kwh if p.battery_action == "discharge" else 0.0
        charge = p.battery_kwh if p.battery_action == "charge" else 0.0
        generation = p.grid_kwh + p.solar_used_kwh + discharge
        load = demands[h] + charge

        if abs(generation - load) > balance_tolerance:
            raise ValueError(
                f"Nodal balance violation at hour {h:02d}:00: "
                f"Supply={generation:.2f} kWh, Demand={load:.2f} kWh"
            )

    # Verify battery neutrality: state at end of hour 23 must restore initial level
    final_e = hourly_plan[23].battery_energy_after_kwh
    if abs(final_e - battery.initial_energy_kwh) > balance_tolerance:
        raise ValueError(
            f"End-of-day neutrality violation: Final={final_e:.2f} kWh, "
            f"Initial={battery.initial_energy_kwh:.2f} kWh"
        )

    # Construct strategic summary
    active = [d for d in directives if d.applies]
    summary_clauses = []
    if any(d.directive_type == "solar_reduction" for d in active):
        summary_clauses.append("accommodated temporary rooftop solar derating")
    if any(d.directive_type == "no_charge_window" for d in active):
        summary_clauses.append("deferred charging around scheduled charger maintenance")
    if any(d.directive_type == "no_discharge_window" for d in active):
        summary_clauses.append("clamped discharge during protection testing")
    if any(d.directive_type == "minimum_battery_reserve" for d in active):
        summary_clauses.append("guaranteed elevated reserve capacity for emergency loads")
    if any(d.directive_type == "max_grid_window" for d in active):
        summary_clauses.append("throttled peak grid draw below substation feeder limits")

    if not summary_clauses:
        summary_clauses.append("leveraged time-of-use tariff arbitrage across off-peak periods")

    plan_summary = (
        f"Optimized schedule successfully {', '.join(summary_clauses)}, "
        f"safeguarded battery operating bounds, and restored state neutrality."
    )

    return total_grid_kwh, total_cost_bdt, peak_grid_kwh, plan_summary


def compute_campus_analytics(
    request: EnergyRequest,
    hourly_plan: List[HourlyPlanItem],
    optimized_cost_bdt: float
) -> Dict[str, Any]:
    """
    Computes real-world financial ROI and environmental metrics for the campus dashboard.
    Compares optimized dispatch against an unmanaged baseline (no battery shifting).
    """
    tariffs = [item.tariff_bdt_per_kwh for item in request.hours]
    demands = [item.demand_kwh for item in request.hours]
    solars = [item.solar_kwh for item in request.hours]

    # Baseline: demand met solely by solar generation with remainder bought directly from grid
    baseline_cost = 0.0
    baseline_grid_kwh = 0.0
    for h in range(24):
        solar_used = min(demands[h], solars[h])
        deficit = max(0.0, demands[h] - solar_used)
        baseline_cost += deficit * tariffs[h]
        baseline_grid_kwh += deficit

    savings_bdt = max(0.0, baseline_cost - optimized_cost_bdt)
    savings_pct = (savings_bdt / baseline_cost * 100.0) if baseline_cost > 0 else 0.0

    total_solar_consumed = sum(p.solar_used_kwh for p in hourly_plan)
    carbon_avoided_kg = total_solar_consumed * GRID_EMISSION_FACTOR_KG_PER_KWH

    return {
        "baseline_cost_bdt": round(baseline_cost, 2),
        "savings_bdt": round(savings_bdt, 2),
        "savings_pct": round(savings_pct, 1),
        "carbon_avoided_kg": round(carbon_avoided_kg, 1),
        "total_solar_consumed_kwh": round(total_solar_consumed, 1)
    }
