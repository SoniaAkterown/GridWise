"""
Input sanitization and directive normalization guardrails.

This module acts as a protective boundary between untrusted generative outputs
and the deterministic LP solver. It validates schemas, maps hour intervals to
the canonical [0, 23] timeline, and converts operator percentage rules into
absolute physical units.
"""

import re
from typing import List, Dict, Any, Optional
from app.schemas import DirectiveInterpretationItem, BatteryInput

ALLOWED_DIRECTIVES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
}


def parse_time_window(text: str) -> List[int]:
    """
    Extracts whole-hour operational windows from operator notes.
    Standard convention: start hour is inclusive, end hour is exclusive.
    e.g., '1 PM to 3 PM' maps to [13, 14].
    """
    t = text.lower()

    # Match 24-hour patterns (e.g., 13:00 to 15:00)
    m_24 = re.search(r'(\d{1,2}):00\s*(?:and|to|until|-)\s*(\d{1,2}):00', t)
    if m_24:
        s, e = int(m_24.group(1)), int(m_24.group(2))
        if 0 <= s < e <= 24:
            return list(range(s, e))

    def to_24(h_str: str, meridiem: Optional[str] = None) -> Optional[int]:
        if not h_str:
            return None
        h_str = h_str.strip().lower()
        if h_str in ("noon", "12 pm"):
            return 12
        if h_str in ("midnight", "12 am"):
            return 0

        word_map = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12
        }
        val = word_map.get(h_str)
        if val is None:
            try:
                val = int(h_str)
            except ValueError:
                return None

        if meridiem == "pm" and val < 12:
            return val + 12
        if meridiem == "am" and val == 12:
            return 0
        return val

    # Match natural language ranges with optional meridiem tokens
    hour_token = r'(?:noon|midnight|\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)'
    p1 = re.search(
        rf'(?:from|between)?\s*({hour_token})\s*(am|pm)?\s*(?:until|to|and|-)\s*({hour_token})\s*(am|pm)?',
        t
    )
    if p1:
        s_raw, s_mer, e_raw, e_mer = p1.groups()

        if s_raw == "noon":
            s_val = 12
        elif s_raw == "midnight":
            s_val = 0
        elif s_mer:
            s_val = to_24(s_raw, s_mer)
        else:
            # Infer missing meridiem from the end token or operational context
            if e_mer == "pm" and to_24(s_raw, None) in (1, 2, 3, 4, 5, 6, 7):
                s_val = to_24(s_raw, "pm")
            elif e_mer == "pm" and to_24(s_raw, None) in (8, 9, 10, 11):
                s_val = to_24(s_raw, "am")
            elif e_raw == "noon":
                s_val = to_24(s_raw, "am")
            else:
                s_val = to_24(s_raw, e_mer)

        if e_raw == "noon":
            e_val = 12
        elif e_raw == "midnight":
            e_val = 24
        else:
            e_val = to_24(e_raw, e_mer)

        if s_val is not None and e_val is not None and s_val < e_val:
            # Shift daylight operational ranges to afternoon if untagged
            if not s_mer and not e_mer and e_raw not in ("noon", "midnight"):
                if any(w in t for w in ["solar", "panel", "pv", "sun", "afternoon"]) or (s_val <= 6 and e_val <= 7):
                    if s_val < 12:
                        s_val += 12
                    if e_val < 12:
                        e_val += 12
            return list(range(s_val, e_val))

    # Pattern for written hours: "from one until three"
    p2 = re.search(
        r'(?:from|between)?\s*(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*(?:until|to|and|-)\s*(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)',
        t
    )
    if p2:
        s_raw, e_raw = p2.groups()
        s_val = to_24(s_raw, None)
        e_val = to_24(e_raw, None)
        if s_val is not None and e_val is not None and s_val < e_val:
            if any(w in t for w in ["solar", "panel", "pv", "sun", "day", "afternoon"]) or (s_val <= 6 and e_val <= 8):
                if s_val <= 12:
                    s_val += 12
                if e_val <= 12:
                    e_val += 12
            return list(range(s_val, e_val))

    return []


def sanitize_hours(raw_hours: Any) -> List[int]:
    """Filters, deduplicates, and sorts hourly intervals within [0, 23]."""
    if not isinstance(raw_hours, list):
        return []
    valid = set()
    for item in raw_hours:
        try:
            h = int(item)
            if 0 <= h <= 23:
                valid.add(h)
        except (ValueError, TypeError):
            continue
    return sorted(list(valid))


def apply_guardrails(
    raw_directives: List[Dict[str, Any]],
    operator_notes: List[str],
    battery: BatteryInput
) -> List[DirectiveInterpretationItem]:
    """
    Enforces canonical invariants on extracted directives before solver injection.
    
    Guarantees:
    - Exactly N directives matching note_index sequence 0..N-1.
    - Strict adherence to allowed directive enums.
    - Deterministic time-window alignment.
    - Physical bounds clamping (solar factor in [0, 1], non-negative reserves).
    - Invariant: no_op requires applies=False and structured_adjustment=None.
    """
    total_notes = len(operator_notes)
    cleaned: List[DirectiveInterpretationItem] = []

    # Index raw extractions by note index
    indexed: Dict[int, Dict[str, Any]] = {}
    for i, item in enumerate(raw_directives):
        idx = item.get("note_index", i)
        if isinstance(idx, int) and 0 <= idx < total_notes and idx not in indexed:
            indexed[idx] = item

    for idx in range(total_notes):
        note_text = operator_notes[idx] if idx < len(operator_notes) else ""
        raw = indexed.get(idx, {})
        d_type = raw.get("directive_type", "no_op")
        if d_type not in ALLOWED_DIRECTIVES:
            d_type = "no_op"

        explanation = str(raw.get("explanation", "")).strip()
        if not explanation:
            explanation = "Directive validated by system guardrails." if d_type != "no_op" else "Note does not alter the 24-hour campus energy schedule."

        # Handle irrelevant / distractor notes
        if d_type == "no_op":
            cleaned.append(
                DirectiveInterpretationItem(
                    note_index=idx,
                    applies=False,
                    directive_type="no_op",
                    structured_adjustment=None,
                    explanation=explanation
                )
            )
            continue

        adj = raw.get("structured_adjustment", {})
        if not isinstance(adj, dict):
            adj = {}

        hours = sanitize_hours(adj.get("hours", []))

        # Reconcile with deterministic time parser to avoid LLM off-by-one errors
        det_hours = parse_time_window(note_text)
        if det_hours:
            if not hours or set(hours).issubset(set(det_hours)) or set(det_hours).issubset(set(hours)) or abs(len(hours) - len(det_hours)) <= 1:
                hours = det_hours

        # 1. Solar reduction factor clamping
        if d_type == "solar_reduction":
            factor_val = adj.get("factor", 1.0)
            try:
                factor = float(factor_val)
                if 1.0 < factor <= 100.0:
                    factor /= 100.0
                factor = max(0.0, min(1.0, factor))
            except (ValueError, TypeError):
                factor = 1.0

            cleaned.append(
                DirectiveInterpretationItem(
                    note_index=idx,
                    applies=True,
                    directive_type="solar_reduction",
                    structured_adjustment={"hours": hours, "factor": round(factor, 4)},
                    explanation=explanation
                )
            )

        # 2. Battery reserve scaling
        elif d_type == "minimum_battery_reserve":
            req_kwh = adj.get("minimum_energy_kwh", battery.minimum_energy_kwh)
            try:
                val = float(req_kwh)
                if 0.0 < val <= 1.0:
                    val *= battery.capacity_kwh
                val = max(0.0, min(battery.capacity_kwh, val))
            except (ValueError, TypeError):
                val = float(battery.minimum_energy_kwh)

            cleaned.append(
                DirectiveInterpretationItem(
                    note_index=idx,
                    applies=True,
                    directive_type="minimum_battery_reserve",
                    structured_adjustment={"hours": hours, "minimum_energy_kwh": round(val, 4)},
                    explanation=explanation
                )
            )

        # 3. Inverter maintenance windows (no-charge / no-discharge)
        elif d_type in ("no_charge_window", "no_discharge_window"):
            cleaned.append(
                DirectiveInterpretationItem(
                    note_index=idx,
                    applies=True,
                    directive_type=d_type,
                    structured_adjustment={"hours": hours},
                    explanation=explanation
                )
            )

        # 4. Feeder import caps
        elif d_type == "max_grid_window":
            grid_cap = adj.get("max_grid_kwh", 1e6)
            try:
                cap = max(0.0, float(grid_cap))
            except (ValueError, TypeError):
                cap = 1e6

            cleaned.append(
                DirectiveInterpretationItem(
                    note_index=idx,
                    applies=True,
                    directive_type="max_grid_window",
                    structured_adjustment={"hours": hours, "max_grid_kwh": round(cap, 4)},
                    explanation=explanation
                )
            )

    return cleaned
