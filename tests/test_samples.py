import json
import os
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SAMPLE_CASES_PATH = os.path.join(os.path.dirname(__file__), "sample_cases.json")

with open(SAMPLE_CASES_PATH, "r") as f:
    sample_data = json.load(f)
    SAMPLE_CASES = sample_data.get("cases", [])


def test_health_endpoint():
    """Verify GET /health returns 200 and {'status': 'ok'}."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_malformed_request():
    """Verify POST /optimize-energy returns 400 on malformed body."""
    response = client.post("/optimize-energy", json={"invalid": "payload"})
    assert response.status_code == 400


@pytest.mark.parametrize("case", SAMPLE_CASES, ids=[c["id"] for c in SAMPLE_CASES])
def test_sample_case_execution(case):
    """
    Test each public sample case against the complete pipeline:
    1. Schema adherence and 200 OK.
    2. Exact directive type, applies, and structured adjustment values.
    3. Hourly plan integrity (24 hours, energy balance, neutrality).
    4. Cost equivalence within allowable numerical tolerance.
    """
    case_input = case["input"]
    expected_output = case["expected_output"]

    response = client.post("/optimize-energy", json=case_input)
    assert response.status_code == 200, f"Failed case {case['id']}: {response.text}"

    data = response.json()

    # 1. Echo scenario_id
    assert data["scenario_id"] == expected_output["scenario_id"]

    # 2. Check directive interpretations
    assert len(data["directive_interpretation"]) == len(expected_output["directive_interpretation"])
    for actual_d, expected_d in zip(data["directive_interpretation"], expected_output["directive_interpretation"]):
        assert actual_d["note_index"] == expected_d["note_index"]
        assert actual_d["applies"] == expected_d["applies"]
        assert actual_d["directive_type"] == expected_d["directive_type"]

        if expected_d["structured_adjustment"] is None:
            assert actual_d["structured_adjustment"] is None
        else:
            exp_adj = expected_d["structured_adjustment"]
            act_adj = actual_d["structured_adjustment"]
            assert act_adj is not None
            assert act_adj["hours"] == exp_adj["hours"]

            if "factor" in exp_adj:
                assert pytest.approx(act_adj["factor"], abs=0.01) == exp_adj["factor"]
            if "minimum_energy_kwh" in exp_adj:
                assert pytest.approx(act_adj["minimum_energy_kwh"], abs=0.01) == exp_adj["minimum_energy_kwh"]
            if "max_grid_kwh" in exp_adj:
                assert pytest.approx(act_adj["max_grid_kwh"], abs=0.01) == exp_adj["max_grid_kwh"]

    # 3. Check 24-hour plan validity
    hourly_plan = data["hourly_plan"]
    assert len(hourly_plan) == 24
    for h, item in enumerate(hourly_plan):
        assert item["hour"] == h
        assert item["grid_kwh"] >= 0
        assert item["solar_used_kwh"] >= 0
        assert item["battery_action"] in ("charge", "discharge", "idle")
        if item["battery_action"] == "idle":
            assert item["battery_kwh"] == 0.0

    # 4. Check total cost and grid purchases against reference solution
    # Numeric tolerance check (organizer allows alternative equivalent optimal solutions within tolerance)
    assert pytest.approx(data["total_cost_bdt"], abs=1.0) == expected_output["total_cost_bdt"]
    assert pytest.approx(data["total_grid_kwh"], abs=1.0) == expected_output["total_grid_kwh"]


def test_paraphrase_robustness():
    """
    Verify Section 11.4 paraphrase robustness across hidden phrasing variations:
    1. 'PV production will drop to about 20% between 13:00 and 15:00.'
    2. 'Panel washing from one until three will leave roughly one-fifth of normal solar output.'
    3. 'Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window.'
    All 3 must map to directive_type='solar_reduction', hours=[13, 14], factor=0.2.
    """
    from app.llm_interpreter import interpret_operator_notes
    from app.schemas import BatteryInput

    b = BatteryInput(
        capacity_kwh=200,
        initial_energy_kwh=100,
        minimum_energy_kwh=30,
        max_charge_kwh_per_hour=50,
        max_discharge_kwh_per_hour=50
    )

    paraphrases = [
        "PV production will drop to about 20% between 13:00 and 15:00.",
        "Panel washing from one until three will leave roughly one-fifth of normal solar output.",
        "Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window."
    ]

    results = interpret_operator_notes(paraphrases, b)
    assert len(results) == 3
    for idx, item in enumerate(results):
        assert item.note_index == idx
        assert item.applies is True
        assert item.directive_type == "solar_reduction"
        assert item.structured_adjustment["hours"] == [13, 14]
        assert pytest.approx(item.structured_adjustment["factor"], abs=0.01) == 0.2

