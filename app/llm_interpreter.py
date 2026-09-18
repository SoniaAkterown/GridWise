"""
Linguistic directive extraction with offline resilience fallback.

Translates free-form campus operator logs into structured operational directives.
Uses Groq's high-throughput LLM API (openai/gpt-oss-120b) with a strict JSON
schema. If upstream network drops, timeouts, or quota throttles occur, execution
transparently falls back to an in-memory rule engine to prevent pipeline disruption.
"""

import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
from groq import Groq
from dotenv import load_dotenv

from app.schemas import BatteryInput, DirectiveInterpretationItem
from app.guardrails import apply_guardrails, parse_time_window

load_dotenv()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert energy systems AI for smart campus microgrid scheduling.
Your task is to analyze natural language operator notes and translate each note into a structured directive for an energy optimizer.

Each request contains 1 to 3 operator notes. You must return a JSON object with a key "directives" containing an array with EXACTLY one object per note in the original order (note_index 0, 1, ...).

The supported directive types are:
1. "solar_reduction":
   - Used when solar / PV output is reduced or dropped due to cloud, cleaning, inverter maintenance, etc.
   - structured_adjustment: {"hours": [list of whole hour ints in ascending order], "factor": remaining_usable_fraction_float}
   - NOTE: "factor" is the remaining usable solar fraction between 0.0 and 1.0!
     * "drop to 20%" or "leave 20%" -> factor = 0.2
     * "80% reduction" -> factor = 0.2 (since 100% - 80% = 20% remaining)
     * "roughly 25%" -> factor = 0.25
     * "about half" -> factor = 0.5

2. "minimum_battery_reserve":
   - Used when emergency reserve or backup energy must remain in the battery.
   - structured_adjustment: {"hours": [list of ints], "minimum_energy_kwh": float}
   - NOTE: If stated as percentage of battery capacity (e.g. "50% of capacity" with 200 kWh capacity), compute the absolute kWh value: 0.5 * 200 = 100.

3. "no_charge_window":
   - Battery charging is prohibited or charger is isolated/unavailable.
   - structured_adjustment: {"hours": [list of ints]}

4. "no_discharge_window":
   - Battery discharging is prohibited (e.g. protection testing, relay testing).
   - structured_adjustment: {"hours": [list of ints]}

5. "max_grid_window":
   - Grid import/intake cannot exceed a certain limit (e.g. feeder cap, transformer limit).
   - structured_adjustment: {"hours": [list of ints], "max_grid_kwh": float}

6. "no_op":
   - The note is irrelevant to today's 24-hour electrical scheduling (e.g. cafeteria menu, registration deadlines, seminar room booking, library hours, club notices).
   - structured_adjustment: null
   - applies: false

TIME WINDOW CONVENTION:
Time windows use whole-hour intervals, start-inclusive and end-exclusive:
- "1 PM to 3 PM" -> [13, 14]
- "noon until 2 PM" -> [12, 13]
- "6 PM until 9 PM" -> [18, 19, 20]
- "2 AM until 5 AM" -> [2, 3, 4]
- "from 6 PM until 10 PM" -> [18, 19, 20, 21]
- "from 7 PM until 9 PM" -> [19, 20]
- "from 7 PM until 10 PM" -> [19, 20, 21]
- "10 AM until noon" -> [10, 11]
- "between 11 AM and 2 PM" -> [11, 12, 13]
Hours must always be sorted in ascending order.

OUTPUT JSON FORMAT:
{
  "directives": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
      "explanation": "Brief explanation"
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "This note does not affect today's energy schedule."
    }
  ]
}
"""


def offline_fallback_extract(
    operator_notes: List[str],
    battery: BatteryInput
) -> List[Dict[str, Any]]:
    """
    Deterministic rule engine serving as a zero-latency offline fallback.
    Maintains 100% contract compliance when upstream API endpoints are unreachable.
    """
    results: List[Dict[str, Any]] = []

    for idx, note in enumerate(operator_notes):
        n_low = note.lower()
        hours = parse_time_window(n_low)

        # Filter administrative campus distractors
        distractor_patterns = [
            "cafeteria", "sports office", "registration", "library", "book-return",
            "student affairs", "club notices", "seminar room", "booking was moved"
        ]
        has_distractor = any(k in n_low for k in distractor_patterns)
        has_power_keyword = any(k in n_low for k in ["battery", "solar", "grid", "feeder", "transformer"])

        if has_distractor and not has_power_keyword:
            results.append({
                "note_index": idx,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "Note refers to general campus operations and has no grid impact."
            })
            continue

        # 1. Solar panel cleaning or cloud derating
        if any(k in n_low for k in ["solar", "pv", "rooftop", "panel"]):
            factor = 0.5
            if "80% reduction" in n_low:
                factor = 0.2
            elif "drop to about 20%" in n_low or "drop to 20%" in n_low or "one-fifth" in n_low:
                factor = 0.2
            elif "25%" in n_low or "one-quarter" in n_low:
                factor = 0.25
            elif "half" in n_low or "50%" in n_low:
                factor = 0.5
            else:
                m_pct = re.search(r'(\d+)%', n_low)
                if m_pct:
                    val = float(m_pct.group(1))
                    factor = round((100.0 - val) / 100.0, 4) if "reduction" in n_low or "reduced by" in n_low else round(val / 100.0, 4)

            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": hours, "factor": factor},
                "explanation": f"Rooftop solar forecast derated to {factor:.2f} residual capacity during maintenance window."
            })

        # 2. Charging circuit lockouts
        elif any(k in n_low for k in ["charger", "charging", "charge"]) and any(k in n_low for k in ["not charge", "do not charge", "unavailable", "isolated", "disabled"]):
            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": "BESS charging isolated for electrical maintenance."
            })

        # 3. Discharging protection / relay testing
        elif any(k in n_low for k in ["discharge", "discharging"]) and any(k in n_low for k in ["not discharge", "do not discharge", "must not discharge", "disabled", "protection", "testing"]):
            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "no_discharge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": "BESS discharge disabled during relay protection tests."
            })

        # 4. Critical load battery reserves
        elif any(k in n_low for k in ["reserve", "stored in the battery", "remain in the battery"]) or ("battery" in n_low and "at least" in n_low):
            min_kwh = battery.minimum_energy_kwh
            m_pct = re.search(r'(\d+)%\s*of\s*(?:the\s*)?battery\s*capacity', n_low)
            if m_pct:
                pct = float(m_pct.group(1)) / 100.0
                min_kwh = pct * battery.capacity_kwh
            else:
                m_kwh = re.search(r'(\d+)\s*kwh', n_low)
                if m_kwh:
                    min_kwh = float(m_kwh.group(1))

            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "minimum_battery_reserve",
                "structured_adjustment": {"hours": hours, "minimum_energy_kwh": min_kwh},
                "explanation": f"Elevated reserve threshold of {min_kwh:.1f} kWh enforced for critical load backup."
            })

        # 5. Substation feeder intake limits
        elif any(k in n_low for k in ["grid import", "grid intake", "feeder", "transformer", "intake must stay"]):
            cap = 1e6
            m_cap = re.search(r'(\d+)\s*kwh', n_low)
            if m_cap:
                cap = float(m_cap.group(1))

            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "max_grid_window",
                "structured_adjustment": {"hours": hours, "max_grid_kwh": cap},
                "explanation": f"Grid import curtailed to {cap:.1f} kWh/h under transformer feeder constraint."
            })

        # Default fallback for unclassified logs
        else:
            results.append({
                "note_index": idx,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "Operator note logged as non-dispatchable context."
            })

    return results


def interpret_operator_notes(
    operator_notes: List[str],
    battery: BatteryInput
) -> List[DirectiveInterpretationItem]:
    """
    Main extraction interface.
    Attempts primary extraction via Groq LLM API with structured output mode.
    Falls back to offline pattern engine upon network timeout or quota exhaustion.
    Directives are passed through deterministic validation before solver injection.
    """
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

    raw_data: Optional[List[Dict[str, Any]]] = None

    if api_key:
        try:
            client = Groq(api_key=api_key)
            payload = {
                "battery_capacity_kwh": battery.capacity_kwh,
                "operator_notes": operator_notes
            }
            completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Extract directives for these notes into a JSON object "
                            f"matching the required schema:\n{json.dumps(payload, indent=2)}"
                        )
                    }
                ],
                model=model,
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=8.0
            )
            content = completion.choices[0].message.content
            parsed = json.loads(content)
            if "directives" in parsed and isinstance(parsed["directives"], list):
                raw_data = parsed["directives"]
            elif isinstance(parsed, list):
                raw_data = parsed
        except Exception as exc:
            logger.warning(f"Groq API call bypassed ({exc}); engaging offline rule engine.")
            raw_data = None

    if raw_data is None:
        raw_data = offline_fallback_extract(operator_notes, battery)

    return apply_guardrails(raw_data, operator_notes, battery)
