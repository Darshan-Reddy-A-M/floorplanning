"""Scorecard, JSON report and text summary built from a ``LayoutSnapshot``.

Thresholds are PROVISIONAL, hand-chosen starting points for the baseline. They
are not derived from RPLAN/CubiCasa5K and will be revisited once the knowledge
layer exists. Hard-constraint failures always make a layout INVALID regardless
of the quality scorecard.
"""

from __future__ import annotations

import json
from typing import Any

from testfit.validation.geometry import run_hard_checks
from testfit.validation.quality import compute_quality
from testfit.validation.snapshot import LayoutSnapshot

FEET_PER_METER = 1 / 0.3048
FEASIBLE_STATUSES = {"OPTIMAL", "FEASIBLE"}

# metric -> (pass_limit, warn_limit); lower is better unless noted.
THRESHOLDS = {
    "void_pct_worst_floor": (10.0, 20.0),
    "vehicle_gate_to_parking_m": (1.0, 4.0),
    "pedestrian_gate_to_door_m": (3.0, 6.0),
    "entrance_room_gap_to_buildable_edge_m": (0.01, 3.0),
    "gate_separation_m_min": 1.5,  # higher is better
    "upper_floor_overhang_m2_max": 0.5,
}
PROVISIONAL_NOTE = (
    "Thresholds are provisional engineering starting points, not dataset-derived."
)


def _grade(value: float | None, limits: tuple[float, float]) -> str:
    if value is None:
        return "n/a"
    if value <= limits[0] + 1e-9:
        return "pass"
    return "warn" if value <= limits[1] + 1e-9 else "fail"


def _entry(metric: str, value: Any, status: str, rule: str) -> dict:
    return {"metric": metric, "value": value, "status": status, "rule": rule}


def build_scorecard(quality: dict) -> list[dict]:
    floors = [f for f in quality["floors"] if f.get("n_rooms")]
    site, reach = quality["site"], quality["reachability"]
    card: list[dict] = []

    worst_void = max((f["void_pct"] for f in floors), default=None)
    t = THRESHOLDS["void_pct_worst_floor"]
    card.append(_entry("void_pct_worst_floor", worst_void, _grade(worst_void, t),
                       f"pass <= {t[0]}%, warn <= {t[1]}% of the floor bounding box"))

    isolated = sum(len(f["isolated_elements"]) for f in floors)
    card.append(_entry("isolated_elements_total", isolated,
                       "pass" if isolated == 0 else "fail",
                       "rooms/stairs touching nothing on their floor"))

    clusters = max((f["clusters_connectable"] for f in floors), default=None)
    card.append(_entry("clusters_per_floor_max", clusters,
                       "n/a" if clusters is None else "pass" if clusters <= 1 else "warn",
                       "groups connected by door-width (>=0.9 m) shared edges; 1 expected for a single dwelling"))

    for key in ("vehicle_gate_to_parking_m", "pedestrian_gate_to_door_m",
                "entrance_room_gap_to_buildable_edge_m"):
        t = THRESHOLDS[key]
        value = site.get(key)
        card.append(_entry(key, value, _grade(value, t), f"pass <= {t[0]} m, warn <= {t[1]} m"))

    sep = site.get("gate_separation_m")
    minimum = THRESHOLDS["gate_separation_m_min"]
    card.append(_entry("gate_separation_m", sep,
                       "n/a" if sep is None else "pass" if sep >= minimum else "warn",
                       f"pass >= {minimum} m between vehicle and pedestrian gates"))

    if quality["stairs"]:
        order = {"circulation": 0, "common_room": 1, "private_or_service_only": 2, "none": 3}
        worst = max(quality["stairs"], key=lambda s: order[s["connection"]])
        status = {"circulation": "pass", "common_room": "warn"}.get(worst["connection"], "fail")
        card.append(_entry("stair_connection_worst_floor", worst["connection"], status,
                           "pass: >=0.9 m edge with foyer/hall; warn: only a living/common room; fail otherwise"))
    else:
        card.append(_entry("stair_connection_worst_floor", None, "n/a", "no staircase"))

    if not reach["entrance_found"]:
        card.append(_entry("unreachable_elements", None, "fail", "entrance room not found on floor 1"))
    else:
        n = len(reach["unreachable"])
        card.append(_entry("unreachable_elements", n, "pass" if n == 0 else "fail",
                           "every room/stair reachable from the entrance via >=0.9 m shared edges"))

    enclosed = sum(len(f["fully_enclosed_habitable"]) for f in floors)
    card.append(_entry("fully_enclosed_habitable_rooms", enclosed,
                       "pass" if enclosed == 0 else "warn",
                       "habitable rooms with no free (exterior or void) wall"))

    over = max(quality["vertical"]["upper_floor_overhang_m2"].values(), default=0.0)
    limit = THRESHOLDS["upper_floor_overhang_m2_max"]
    card.append(_entry("upper_floor_overhang_m2_max", over,
                       "pass" if over <= limit else "warn",
                       f"upper-floor area outside the ground-floor footprint (pass <= {limit} m2)"))
    return card


def evaluate(snapshot: LayoutSnapshot, snapshot_id: str = "") -> dict:
    """Run every hard check and quality metric on the actual coordinates."""
    base = {"id": snapshot_id, "solver_status": snapshot.status,
            "thresholds_note": PROVISIONAL_NOTE}
    if snapshot.status not in FEASIBLE_STATUSES or not snapshot.rooms:
        return {**base, "verdict": "NO_LAYOUT", "hard_pass": False, "hard_checks": [],
                "quality": None, "scorecard": [],
                "summary": {"pass": 0, "warn": 0, "fail": 0}}
    checks = run_hard_checks(snapshot)
    hard_pass = all(c.passed for c in checks)
    quality = compute_quality(snapshot)
    card = build_scorecard(quality)
    counts = {k: sum(e["status"] == k for e in card) for k in ("pass", "warn", "fail")}
    verdict = "INVALID" if not hard_pass else "OK" if counts["fail"] == 0 else "VALID_POOR_QUALITY"
    return {**base, "verdict": verdict, "hard_pass": hard_pass,
            "hard_checks": [c.to_dict() for c in checks],
            "quality": quality, "scorecard": card, "summary": counts}


def to_json(report: dict) -> str:
    return json.dumps(report, indent=2, default=str)


def _fmt(value: Any, unit: str) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)) and unit == "m":
        return f"{value:.2f} m ({value * FEET_PER_METER:.1f} ft)"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def format_text(report: dict) -> str:
    lines = [f"[{report['id']}] solver={report['solver_status']} verdict={report['verdict']}"]
    for c in report["hard_checks"]:
        if not c["passed"]:
            lines.append(f"  HARD FAIL {c['name']}: " + "; ".join(c["violations"][:5]))
    for e in report["scorecard"]:
        unit = "m" if e["metric"].endswith("_m") else ""
        lines.append(f"  {e['status'].upper():5} {e['metric']}: {_fmt(e['value'], unit)}")
    return "\n".join(lines)


SUMMARY_COLUMNS = (
    "id", "solver_status", "verdict", "seconds", "n_rooms", "void_pct_worst_floor",
    "isolated_elements_total", "clusters_per_floor_max", "vehicle_gate_to_parking_m",
    "pedestrian_gate_to_door_m", "entrance_room_gap_to_buildable_edge_m",
    "stair_connection_worst_floor", "unreachable_elements",
    "fully_enclosed_habitable_rooms", "upper_floor_overhang_m2_max", "hard_failures",
)


def summary_row(report: dict, seconds: float | None = None, n_rooms: int | None = None) -> dict:
    """One flat row of headline metrics for CSV/Markdown comparison tables."""
    values = {e["metric"]: e["value"] for e in report["scorecard"]}
    row = {
        "id": report["id"],
        "solver_status": report["solver_status"],
        "verdict": report["verdict"],
        "seconds": seconds,
        "n_rooms": n_rooms,
        "hard_failures": ";".join(c["name"] for c in report["hard_checks"] if not c["passed"]),
    }
    for column in SUMMARY_COLUMNS:
        if column not in row:
            row[column] = values.get(column)
    return row


def rows_to_markdown(rows: list[dict]) -> str:
    def cell(value: Any) -> str:
        if value is None or value == "":
            return "-"
        return f"{value:.2f}" if isinstance(value, float) else str(value)

    lines = ["| " + " | ".join(SUMMARY_COLUMNS) + " |",
             "|" + "|".join("---" for _ in SUMMARY_COLUMNS) + "|"]
    lines += ["| " + " | ".join(cell(r.get(c)) for c in SUMMARY_COLUMNS) + " |" for r in rows]
    return "\n".join(lines)
