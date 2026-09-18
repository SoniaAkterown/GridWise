# GridWise — Autonomous Campus Microgrid Energy Management System
**BUP CSE Fest 2026 Hackathon · Smart Campus Energy Optimization Challenge**
**Team: DIU Artificial Idiots**

---

## 1. Executive Summary & Problem Formulation

Modern educational and research campuses operate complex microgrids combining variable rooftop photovoltaic (PV) arrays, Battery Energy Storage Systems (BESS), and national utility grid interconnects subject to dynamic Time-of-Use (TOU) tariffs. 

The **Smart Campus Energy Optimization Challenge** requires an autonomous microservice capable of:
1. Ingesting 24-hour numerical forecasts of campus electrical load demand, rooftop solar generation, and hourly utility electricity tariffs.
2. Interpreting 1 to 3 unstructured, natural-language operational logbook notes written by human shift operators (e.g. equipment maintenance, dust cleaning deratings, emergency reserve requirements, or irrelevant chatter).
3. Formulating and solving a continuous economic dispatch optimization problem to minimize the campus's total 24-hour electricity bill in Bangladeshi Taka (BDT).
4. Strictly upholding physical power balance, energy storage state continuity, battery capacity bounds, operational directive constraints, and end-of-day battery neutrality ($E_{23} \ge E_0$).

GridWise solves this challenge through a decoupled architecture governed by the design principle:
> **"Deterministic rules guard the math; generative models parse the language."**

---

## 2. System Architecture

```
                                  HTTP Request
                       (POST /optimize-energy or Web Console)
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. FastAPI Ingestion & Schema Validation Layer                              │
│    - Enforces canonical Pydantic v2 schemas and strict bounds checks        │
│    - Validates 24-hour vector lengths, non-negative flows, battery envelope │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. Generative Linguistic Parser (NLP Engine)                                │
│    - Primary: Groq LPU Inference (Llama-3.3-70B / GPT-OSS-120B)             │
│    - Zero-shot JSON directive extraction from human operator logbook notes  │
│    - Fallback: Offline Deterministic Regex NLP Engine (0% outage risk)      │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. Deterministic Guardrail Shield Layer                                     │
│    - Normalizes hour intervals into strictly sorted, unique arrays [0..23]  │
│    - Enforces physical parameter bounds (solar factor in [0.0, 1.0])        │
│    - Converts relative reserve percentages to absolute kWh                  │
│    - Filters distractor / irrelevant notes (applies=false, adjustment=null) │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. Mathematical Continuous LP Solver (SciPy HiGHS)                          │
│    - Formulates 120-variable continuous Linear Program (5 state vars / hour)│
│    - Imposes hourly power balance, storage continuity, reserve floors       │
│    - Solves to global mathematical optimality in under 3.0 milliseconds     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. Physical Invariant Auditor & Serializer                                  │
│    - Replays dispatch schedule against independent physical equations       │
│    - Validates energy balance with residual error < 0.00001 kWh             │
│    - Verifies end-of-day battery neutrality (E_23 >= E_0)                   │
│    - Computes campus financial ROI and carbon abatement telemetry           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
                            Structured Response JSON
```

---

## 3. Mathematical Model & Linear Programming Formulation

The dispatch optimization is formulated as a 24-hour continuous Linear Program (LP) over the discrete horizon $H = \{0, 1, \dots, 23\}$.

### 3.1 State Representation & Decision Variables

For each hour $h \in H$, the system models 5 continuous decision variables (120 variables total):
- $G_h \ge 0$: Electrical power imported from the national utility grid (kWh).
- $S_h \ge 0$: Rooftop solar PV generation consumed directly by campus load (kWh).
- $C_h \ge 0$: Energy dispatched to charge the BESS (kWh).
- $D_h \ge 0$: Energy dispatched from the BESS to supply campus load (kWh).
- $E_h \ge 0$: Energy stored in the BESS at the conclusion of hour $h$ (kWh).

### 3.2 Objective Function

Minimize the total electricity procurement cost over the 24-hour scheduling window:

$$\min_{G, S, C, D, E} \quad \sum_{h=0}^{23} \left( \text{Tariff}_h \cdot G_h + \epsilon_{\text{wear}} \cdot (C_h + D_h) \right)$$

where $\text{Tariff}_h$ is the dynamic grid electricity price in BDT/kWh, and $\epsilon_{\text{wear}} = 10^{-5}$ is an infinitesimal battery degradation regularization term that prevents simultaneous micro-charging and discharging.

### 3.3 Governing Constraints

1. **Hourly Nodal Power Balance**:
   At every hour $h$, the sum of generation and storage discharge must satisfy the campus demand:
   $$G_h + S_h + D_h - C_h = \text{Demand}_h, \quad \forall h \in H$$

2. **BESS Dynamic State Continuity**:
   Battery stored energy evolves deterministically based on charge and discharge flows:
   $$E_0 = E_{\text{init}} + C_0 - D_0$$
   $$E_h = E_{h-1} + C_h - D_h, \quad \forall h \in \{1, \dots, 23\}$$

3. **Battery Energy Capacity & Reserve Envelope**:
   The stored energy must remain between the physical minimum reserve floor and rated capacity:
   $$E_{\min, h} \le E_h \le \text{Capacity}_{\text{batt}}, \quad \forall h \in H$$

4. **Battery Power Inverter Limits**:
   Charge and discharge rates are physically bounded by the BESS power conversion system:
   $$0 \le C_h \le C_{\max, h}, \quad 0 \le D_h \le D_{\max, h}, \quad \forall h \in H$$

5. **End-of-Day Neutrality**:
   To preserve operational readiness for the subsequent day, the final stored energy must equal or exceed the initial state:
   $$E_{23} \ge E_{\text{init}}$$

6. **Solar Availability & Directive Deratings**:
   Usable rooftop generation cannot exceed the derated solar forecast:
   $$0 \le S_h \le \text{Factor}_h \cdot \text{SolarForecast}_h, \quad \forall h \in H$$

7. **Utility Substation Feeder Ceiling**:
   Grid imports cannot exceed substation transformer feeder ratings:
   $$0 \le G_h \le G_{\max, h}, \quad \forall h \in H$$

---

## 4. Supported Directive Classes

The generative linguistic parser and deterministic shield recognize and enforce six standardized operator directive types:

| Directive Type | Description | Mathematical Impact |
| :--- | :--- | :--- |
| `solar_reduction` | Rooftop solar array washing, dust storms, or maintenance deratings. | Scales available solar: $S_h \le \text{factor} \cdot \text{Solar}_h$ for designated hours. |
| `minimum_battery_reserve` | Emergency backup reservations for events, exams, or server rooms. | Elevates lower bound: $E_h \ge \text{reserve\_kwh}$. Converts percentage capacity to absolute kWh. |
| `no_charge_window` | Charger inspection, grid stress, or peak avoidance windows. | Clamps charging flow: $C_h = 0$ for designated hours. |
| `no_discharge_window` | Inverter protection testing, battery diagnostics, or testing. | Clamps discharge flow: $D_h = 0$ for designated hours. |
| `max_grid_window` | Substation transformer maintenance or peak shaving demand caps. | Caps grid intake: $G_h \le \text{max\_draw\_kw}$ for designated hours. |
| `no_op` | Distractor notes, campus announcements, cafeteria notices. | Ignored: `applies = false`, `structured_adjustment = null`. |

*Time Convention*: Hour ranges are start-inclusive and end-exclusive (e.g., "11 AM to 2 PM" corresponds to hours `[11, 12, 13]`).

---

## 5. Technology Stack & Implementation Details

| Layer | Component | Technical Selection & Rationale |
| :--- | :--- | :--- |
| **Microservice Core** | FastAPI & Uvicorn | Asynchronous ASGI framework providing native Pydantic v2 validation, sub-millisecond route dispatch, and auto-generated OpenAPI documentation. |
| **NLP Inference** | Groq LPU API | Accelerated inference engine executing Llama-3.3-70B and GPT-OSS-120B with typical latencies of 800–1100 ms. |
| **Resilience Fallback** | Deterministic Regex NLP | Offline rule-based linguistic extraction engine guaranteeing zero downtime and 100% test pass rate even during external API outages. |
| **Mathematical Solver** | SciPy HiGHS (`method='highs'`) | Native continuous dual-simplex Linear Programming solver; guarantees global cost optimality in 2–3 ms without external C++ binary dependencies. |
| **Telemetry & Visuals** | Chart.js & Tailwind CSS | Clean, humanized dashboard featuring a 24-hour simulation scrubber, topology deck, liquid battery gauge, and mathematical invariant proof inspector. Zero emojis. |
| **Containerization** | Docker (`python:3.11-slim`) | Lightweight container footprint (~180MB) with strict non-root security boundaries. |

---

## 6. Project Directory Layout

```
.
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI endpoints (/optimize-energy, /health, /api/quick-solve)
│   ├── schemas.py             # Canonical Pydantic v2 data models & validation
│   ├── llm_interpreter.py     # Groq API client with structured prompts & regex fallback
│   ├── guardrails.py          # Deterministic parameter sanitization & bounds clamping
│   ├── optimizer.py           # SciPy HiGHS LP formulation & continuous solver
│   └── validator.py           # Physical replay auditor & financial ROI analytics
├── static/
│   ├── index.html             # Humanized BUP Campus EMS console & simulation deck
│   ├── style.css              # Custom styling, glassmorphic cards, liquid battery gauge
│   └── app.js                 # Interactive client controller, multi-mode Chart.js, telemetry
├── tests/
│   ├── __init__.py
│   ├── sample_cases.json      # 10 canonical public reference scenarios
│   └── test_samples.py        # Automated pytest integration test suite (13/13 tests)
├── Dockerfile                 # Multi-stage production container build
├── requirements.txt           # Pinned Python dependencies
├── .env.example               # Environment configuration template
└── README.md                  # System documentation & architectural reference
```

---

## 7. Quickstart Guide

### 7.1 Local Python Installation

#### Prerequisites
- Python 3.10, 3.11, or 3.12
- Git

#### Installation Steps
```bash
# 1. Clone the repository
git clone https://github.com/your-username/gridwise-optimizer.git
cd gridwise-optimizer

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
```

Edit `.env` to configure your settings:
```ini
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b
PORT=8000
HOST=0.0.0.0
```
*(Note: If `GROQ_API_KEY` is omitted or left empty, the application seamlessly operates in resilient offline mode using the deterministic rule engine with 100% test coverage).*

#### Running the Service
```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Once running, access the interactive dashboard at: `http://localhost:8000/`

---

### 7.2 Docker Deployment

#### Build the Image
```bash
docker build -t gridwise-optimizer:latest .
```

#### Run the Container
```bash
docker run -d \
  --name gridwise \
  -p 8000:8000 \
  -e GROQ_API_KEY="gsk_your_groq_api_key_here" \
  gridwise-optimizer:latest
```

Verify container health:
```bash
curl http://localhost:8000/health
```

---

## 8. Automated Test Suite & Benchmark Results

The automated integration suite (`tests/test_samples.py`) evaluates the entire pipeline across all 10 canonical competition scenarios plus paraphrase edge cases:

```bash
PYTHONPATH=. pytest tests/test_samples.py -v
```

### Test Execution Summary

```
tests/test_samples.py::test_health_endpoint PASSED                       [  7%]
tests/test_samples.py::test_malformed_request PASSED                     [ 15%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-01] PASSED      [ 23%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-02] PASSED      [ 30%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-03] PASSED      [ 38%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-04] PASSED      [ 46%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-05] PASSED      [ 53%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-06] PASSED      [ 61%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-07] PASSED      [ 69%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-08] PASSED      [ 76%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-09] PASSED      [ 84%]
tests/test_samples.py::test_sample_case_execution[SAMPLE-10] PASSED      [ 92%]
tests/test_samples.py::test_paraphrase_robustness PASSED                 [100%]

======================== 13 passed in 25.53s ========================
```

- **Pass Rate**: 13/13 (100%)
- **Mathematical Error Tolerance**: Maximum energy balance residual $< 0.00001$ kWh across all 240 simulated hours.
- **LP Solver Latency**: Consistently between 2.0 and 3.2 ms per 24-hour horizon.

---

## 9. API Reference & Specification

### 9.1 Service Health Probe
**Endpoint:** `GET /health`  
**Description:** Health check endpoint for automated judging harnesses.

#### Response:
```json
{
  "status": "ok"
}
```

---

### 9.2 Energy Optimization Pipeline
**Endpoint:** `POST /optimize-energy`  
**Description:** Ingests 24-hour campus forecasts and unstructured operator logbook notes, returning parsed directives and the optimal 24-hour dispatch schedule.

#### Sample Request:
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "SAMPLE-01",
    "operator_notes": [
      "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
      "The sports office moved next months registration deadline."
    ],
    "hours": [
      {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 2, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 3, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 4, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 5, "demand_kwh": 95, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 6, "demand_kwh": 110, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
      {"hour": 7, "demand_kwh": 130, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
      {"hour": 8, "demand_kwh": 150, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
      {"hour": 9, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
      {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
      {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
      {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
      {"hour": 14, "demand_kwh": 170, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
      {"hour": 15, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 16, "demand_kwh": 170, "solar_kwh": 45, "tariff_bdt_per_kwh": 18},
      {"hour": 17, "demand_kwh": 185, "solar_kwh": 10, "tariff_bdt_per_kwh": 22},
      {"hour": 18, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 28},
      {"hour": 19, "demand_kwh": 215, "solar_kwh": 0, "tariff_bdt_per_kwh": 30},
      {"hour": 20, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 26},
      {"hour": 21, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
      {"hour": 22, "demand_kwh": 135, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
      {"hour": 23, "demand_kwh": 105, "solar_kwh": 0, "tariff_bdt_per_kwh": 7}
    ],
    "battery": {
      "capacity_kwh": 220,
      "initial_energy_kwh": 110,
      "minimum_energy_kwh": 40,
      "max_charge_kwh_per_hour": 50,
      "max_discharge_kwh_per_hour": 50
    }
  }'
```

#### Sample Response Structure:
```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {
        "hours": [12, 13],
        "factor": 0.25
      },
      "explanation": "Solar output reduced to 25% of forecast during panel cleaning window hours 12-13."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "Notice regarding sports registration deadline does not impact energy dispatch."
    }
  ],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 90.0,
      "solar_used_kwh": 0.0,
      "battery_action": "idle",
      "battery_kwh": 0.0,
      "battery_energy_after_kwh": 110.0
    },
    ...
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 190.0,
  "plan_summary": "Charged BESS during off-peak morning hours and discharged during evening peak tariff window."
}
```

---

### 9.3 Sub-Millisecond What-If Re-Optimization
**Endpoint:** `POST /api/quick-solve`  
**Description:** Re-optimizes the continuous LP using pre-extracted directives in under 3.5 ms for real-time slider interactions.

---

### 9.4 Telemetry and Diagnostics
- `GET /metrics`: Live process memory (RSS MB), CPU usage %, and recent solver latency.
- `GET /api/test-summary`: Summary of automated test coverage (13/13 passing, 100% pass rate).
- `GET /api/sample-cases`: Canonical challenge scenarios (SAMPLE-01 to SAMPLE-10).

---

## 10. Security & Quality Attributes

- **Zero Secret Disclosure**: No API keys or tokens are tracked in git or baked into Docker layers. Configuration is strictly environment-driven via `.env`.
- **Fault-Tolerant Resilience**: If the Groq API experiences network timeouts or rate limits, the deterministic fallback engine immediately assumes parsing duties with zero interruption.
- **Strict Data Sanitization**: Error handlers catch and sanitize all validation exceptions into structured HTTP 400 or HTTP 500 JSON without leaking system paths or stack traces.
- **Mathematical Determinism**: SciPy HiGHS guarantees identical, globally optimal solutions across runs given the same constraints.

---

## 11. License & Team Information

Developed for the **BUP CSE Fest 2026 Hackathon** · Preliminary Round  
**Project**: GridWise — Smart Campus Energy Optimization Platform  
**Team**: DIU Artificial Idiots  
**Copyright**: (c) 2026 GridWise by DIU Artificial Idiots. All rights reserved.
