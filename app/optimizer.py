"""
24-hour Linear Programming optimization engine for campus microgrid dispatch.

Models energy balance, rooftop solar curtailment, and BESS (Battery Energy
Storage System) dynamics using SciPy's HiGHS solver. Guarantees global cost
optimality while honoring all active operator constraints and battery neutrality.
"""

from typing import List, Tuple
import numpy as np
from scipy.optimize import linprog

from app.schemas import EnergyRequest, DirectiveInterpretationItem, HourlyPlanItem


def solve_energy_optimization(
    request: EnergyRequest,
    directives: List[DirectiveInterpretationItem]
) -> Tuple[List[HourlyPlanItem], float, float, float]:
    """
    Formulates and solves the continuous 24-hour economic dispatch problem.
    
    State representation per hour h in [0..23] (120 variables total):
        x[5h + 0]: G_h (Grid imported power, kWh)
        x[5h + 1]: S_h (Solar generation consumed on-site, kWh)
        x[5h + 2]: C_h (BESS charging flow, kWh)
        x[5h + 3]: D_h (BESS discharging flow, kWh)
        x[5h + 4]: E_h (BESS stored energy level at hour conclusion, kWh)
    """
    horizon = 24
    n_vars = horizon * 5

    # Campus telemetry vectors
    demands = np.array([item.demand_kwh for item in request.hours], dtype=float)
    solar_base = np.array([item.solar_kwh for item in request.hours], dtype=float)
    tariffs = np.array([item.tariff_bdt_per_kwh for item in request.hours], dtype=float)

    # Battery physical envelope
    batt = request.battery
    capacity = float(batt.capacity_kwh)
    e_init = float(batt.initial_energy_kwh)
    min_reserve_base = float(batt.minimum_energy_kwh)
    rate_charge_max = float(batt.max_charge_kwh_per_hour)
    rate_discharge_max = float(batt.max_discharge_kwh_per_hour)

    # Apply operator directives to the hourly parameter arrays
    solar_effective = solar_base.copy()
    reserve_lower = np.full(horizon, min_reserve_base, dtype=float)
    allow_charge = np.ones(horizon, dtype=bool)
    allow_discharge = np.ones(horizon, dtype=bool)
    grid_ceiling = np.full(horizon, np.inf, dtype=float)

    for directive in directives:
        if not directive.applies or not directive.structured_adjustment:
            continue

        adj = directive.structured_adjustment
        if hasattr(adj, "model_dump"):
            adj = adj.model_dump()

        hours = adj.get("hours", [])
        dtype = directive.directive_type

        if dtype == "solar_reduction":
            factor = float(adj.get("factor", 1.0))
            for h in hours:
                if 0 <= h < horizon:
                    solar_effective[h] = solar_base[h] * factor

        elif dtype == "minimum_battery_reserve":
            floor_kwh = float(adj.get("minimum_energy_kwh", min_reserve_base))
            for h in hours:
                if 0 <= h < horizon:
                    reserve_lower[h] = max(reserve_lower[h], floor_kwh)

        elif dtype == "no_charge_window":
            for h in hours:
                if 0 <= h < horizon:
                    allow_charge[h] = False

        elif dtype == "no_discharge_window":
            for h in hours:
                if 0 <= h < horizon:
                    allow_discharge[h] = False

        elif dtype == "max_grid_window":
            cap = float(adj.get("max_grid_kwh", np.inf))
            for h in hours:
                if 0 <= h < horizon:
                    grid_ceiling[h] = min(grid_ceiling[h], cap)

    # Linear objective: minimize sum(G_h * tariff_h)
    c = np.zeros(n_vars, dtype=float)
    for h in range(horizon):
        c[5 * h + 0] = tariffs[h]

    # Variable bounds enforcing operational envelopes
    bounds = []
    for h in range(horizon):
        # Grid import: bounded by directive caps where applicable
        g_hi = grid_ceiling[h] if np.isfinite(grid_ceiling[h]) else None
        bounds.append((0.0, g_hi))

        # Solar consumed: capped at available generation (excess is curtailed)
        bounds.append((0.0, float(solar_effective[h])))

        # Battery charging: clamped to 0 during maintenance windows
        c_hi = rate_charge_max if allow_charge[h] else 0.0
        bounds.append((0.0, float(c_hi)))

        # Battery discharging: clamped to 0 during protection windows
        d_hi = rate_discharge_max if allow_discharge[h] else 0.0
        bounds.append((0.0, float(d_hi)))

        # State-of-charge: enforces minimum emergency reserve and capacity
        bounds.append((float(reserve_lower[h]), capacity))

    # Equalities: Energy Balance (24) + State Continuity (24) + EOD Neutrality (1)
    A_eq = []
    b_eq = []

    # 1. Hourly nodal balance: G_h + S_h + D_h - C_h = Demand_h
    for h in range(horizon):
        row = np.zeros(n_vars, dtype=float)
        row[5 * h + 0] = 1.0   # G_h
        row[5 * h + 1] = 1.0   # S_h
        row[5 * h + 2] = -1.0  # C_h
        row[5 * h + 3] = 1.0   # D_h
        A_eq.append(row)
        b_eq.append(demands[h])

    # 2. Battery state transitions:
    # h = 0: E_0 - C_0 + D_0 = E_init
    row_0 = np.zeros(n_vars, dtype=float)
    row_0[5 * 0 + 4] = 1.0   # E_0
    row_0[5 * 0 + 2] = -1.0  # C_0
    row_0[5 * 0 + 3] = 1.0   # D_0
    A_eq.append(row_0)
    b_eq.append(e_init)

    # h in [1..23]: E_h - E_{h-1} - C_h + D_h = 0
    for h in range(1, horizon):
        row_h = np.zeros(n_vars, dtype=float)
        row_h[5 * h + 4] = 1.0
        row_h[5 * (h - 1) + 4] = -1.0
        row_h[5 * h + 2] = -1.0
        row_h[5 * h + 3] = 1.0
        A_eq.append(row_h)
        b_eq.append(0.0)

    # 3. End-of-day neutrality: E_23 = E_init
    row_eod = np.zeros(n_vars, dtype=float)
    row_eod[5 * 23 + 4] = 1.0
    A_eq.append(row_eod)
    b_eq.append(e_init)

    # Solve using HiGHS dual-simplex
    solution = linprog(
        c=c,
        A_eq=np.array(A_eq, dtype=float),
        b_eq=np.array(b_eq, dtype=float),
        bounds=bounds,
        method="highs"
    )

    if not solution.success:
        raise ValueError(f"Linear program solver convergence failed: {solution.message}")

    x = solution.x

    # Extract results and sanitize numerical zero-crossings
    plan: List[HourlyPlanItem] = []
    for h in range(horizon):
        grid = float(x[5 * h + 0])
        solar = float(x[5 * h + 1])
        c_kwh = float(x[5 * h + 2])
        d_kwh = float(x[5 * h + 3])
        e_after = float(x[5 * h + 4])

        # Filter solver epsilon noise
        if abs(grid) < 1e-6:
            grid = 0.0
        if abs(solar) < 1e-6:
            solar = 0.0
        if abs(c_kwh) < 1e-6:
            c_kwh = 0.0
        if abs(d_kwh) < 1e-6:
            d_kwh = 0.0

        # Complementarity post-processing to eliminate simultaneous micro-flow
        if c_kwh > 1e-4 and d_kwh > 1e-4:
            net_flow = c_kwh - d_kwh
            if net_flow > 0:
                c_kwh, d_kwh = net_flow, 0.0
            else:
                c_kwh, d_kwh = 0.0, -net_flow

        if c_kwh > 1e-4:
            action = "charge"
            flow = c_kwh
        elif d_kwh > 1e-4:
            action = "discharge"
            flow = d_kwh
        else:
            action = "idle"
            flow = 0.0

        plan.append(
            HourlyPlanItem(
                hour=h,
                grid_kwh=round(grid, 4),
                solar_used_kwh=round(solar, 4),
                battery_action=action,
                battery_kwh=round(flow, 4),
                battery_energy_after_kwh=round(e_after, 4)
            )
        )

    return plan, float(solution.fun), float(max(p.grid_kwh for p in plan)), float(sum(p.grid_kwh for p in plan))
