#!/usr/bin/env python
"""Run the current solver on the sample matrix and measure every layout.

This changes no solver behavior. It calls ``solve_layout`` exactly as app.py does
(Automatic Room Recommendation -> accept -> generate), re-checks the returned
coordinates with the independent validator, and writes JSON, PNG and summary
files. Requires OR-Tools and matplotlib.

    python scripts/generate_samples.py --out reports/baseline --time-limit 5
    python scripts/generate_samples.py --only rental --out /tmp/try
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import platform
import sys
import time
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="reports/baseline", help="output directory")
    parser.add_argument("--time-limit", type=float, default=5.0,
                        help="solver seconds per layout (app default is 5)")
    parser.add_argument("--only", default="", help="substring filter on config ids")
    parser.add_argument("--no-images", action="store_true")
    return parser.parse_args()


def build_inputs(cfg):
    from testfit.defaults import DEFAULT_RELATIONSHIPS, DEFAULT_ROOMS
    from testfit.planning import (
        PARKING_DEFAULT_FEET, STAIRCASE_DEFAULT_FEET, feet_to_meters,
        recommend_room_program, setback_bounds_feet,
    )

    width_ft, length_ft = cfg.site_ft
    bounds_ft = setback_bounds_feet(width_ft, length_ft, cfg.road_access, *cfg.setbacks_ft)
    parking_ft = PARKING_DEFAULT_FEET.get(cfg.parking)
    stair_ft = STAIRCASE_DEFAULT_FEET
    if cfg.mode == "default_custom":
        rooms, relationships = list(DEFAULT_ROOMS), list(DEFAULT_RELATIONSHIPS)
    else:
        rooms, relationships, _ = recommend_room_program(
            buildable_bounds_ft=bounds_ft,
            number_of_floors=cfg.floors,
            building_type=cfg.building_type,
            units_per_floor=cfg.units_per_floor,
            parking_area_ft2=parking_ft[0] * parking_ft[1] if parking_ft else 0.0,
            staircase_size_ft=stair_ft,
        )
    return {
        "rooms": rooms,
        "relationships": relationships,
        "site_m": (feet_to_meters(width_ft), feet_to_meters(length_ft)),
        "bounds_m": tuple(feet_to_meters(v) for v in bounds_ft),
        "parking_m": None if parking_ft is None else tuple(feet_to_meters(v) for v in parking_ft),
        "stair_m": tuple(feet_to_meters(v) for v in stair_ft),
    }


def display_placement(placement):
    from testfit.optimizer import Placement
    from testfit.planning import meters_to_feet

    return Placement(placement.name, meters_to_feet(placement.x), meters_to_feet(placement.y),
                     meters_to_feet(placement.width), meters_to_feet(placement.length),
                     placement.floor, placement.floor_end)


def render(cfg, inputs, result, entrance_room, out_dir: pathlib.Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from testfit.planning import meters_to_feet
    from testfit.visualization import create_floor_plan

    written = []
    entrance_side = cfg.entrance_side or cfg.road_access
    for floor in range(1, result.number_of_floors + 1):
        figure = create_floor_plan(
            cfg.site_ft[0], cfg.site_ft[1],
            [display_placement(p) for p in result.placements if p.floor == floor],
            floor_number=floor,
            parking=display_placement(result.parking) if result.parking else None,
            staircases=[display_placement(s) for s in result.staircases],
            buildable_bounds=tuple(meters_to_feet(v) for v in inputs["bounds_m"]),
            road_access=cfg.road_access,
            entrance_room_name=entrance_room.name if entrance_room else None,
            entrance_side=entrance_side,
            relationships=inputs["relationships"],
            unit_label="ft",
        )
        name = f"{cfg.id}_floor{floor}.png"
        figure.savefig(out_dir / name, dpi=110)
        plt.close(figure)
        written.append(name)
    return written


def run_config(cfg, args, out_dir: pathlib.Path) -> dict:
    from testfit.optimizer import solve_layout
    from testfit.planning import select_entrance_room
    from testfit.validation import (
        as_rect, evaluate, legacy_gate_points, snapshot_from_layout, summary_row,
    )

    inputs = build_inputs(cfg)
    parking = inputs["parking_m"]
    started = time.monotonic()
    result = solve_layout(
        inputs["site_m"][0], inputs["site_m"][1], inputs["rooms"],
        relationships=inputs["relationships"],
        number_of_floors=cfg.floors,
        parking_type=cfg.parking,
        parking_width=parking[0] if parking else None,
        parking_length=parking[1] if parking else None,
        road_access=cfg.road_access,
        staircase_width=inputs["stair_m"][0],
        staircase_length=inputs["stair_m"][1],
        buildable_bounds=inputs["bounds_m"],
        time_limit_seconds=args.time_limit,
    )
    seconds = time.monotonic() - started

    entrance_side = cfg.entrance_side or cfg.road_access
    entrance_room = select_entrance_room(result.placements, entrance_side) if result.placements else None
    snapshot = snapshot_from_layout(
        result,
        site_width=inputs["site_m"][0], site_length=inputs["site_m"][1],
        relationships=inputs["relationships"], buildable_bounds=inputs["bounds_m"],
        entrance_side=entrance_side,
        entrance_room=entrance_room.name if entrance_room else None,
        expected_rooms=inputs["rooms"],
        expected_parking=parking,
        expected_staircase=inputs["stair_m"] if cfg.floors > 1 else None,
        meta={"config_id": cfg.id, "solver_message": result.message, "solver_seconds": seconds,
              "time_limit": args.time_limit},
    )
    if result.placements:
        points = legacy_gate_points(
            site_width=snapshot.site_width, site_length=snapshot.site_length,
            road_access=cfg.road_access, entrance_side=entrance_side,
            parking=snapshot.parking, entrance_room=as_rect(entrance_room) if entrance_room else None,
        )
        snapshot.vehicle_gate = points["vehicle_gate"]
        snapshot.pedestrian_gate = points["pedestrian_gate"]
        snapshot.entrance_door = points["entrance_door"]
        snapshot.gate_source = "legacy_projection"

    report = evaluate(snapshot, cfg.id)
    images = []
    if result.placements and not args.no_images:
        images = render(cfg, inputs, result, entrance_room, out_dir)
    record = {
        "config": cfg.__dict__,
        "solver": {"status": result.status, "message": result.message, "seconds": seconds},
        "images": images,
        "snapshot": snapshot.to_dict(),
        "report": report,
    }
    (out_dir / f"{cfg.id}.json").write_text(json.dumps(record, indent=2, default=str))
    return summary_row(report, seconds=round(seconds, 2), n_rooms=len(snapshot.rooms))


def main() -> int:
    args = parse_args()
    from ortools import __version__ as ortools_version
    from testfit.validation import SUMMARY_COLUMNS, rows_to_markdown
    from tests.fixtures.sample_configs import SAMPLE_CONFIGS

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    configs = [c for c in SAMPLE_CONFIGS if args.only in c.id]
    rows, errors = [], []
    for cfg in configs:
        print(f"== {cfg.id}: {cfg.description}", flush=True)
        try:
            row = run_config(cfg, args, out_dir)
        except Exception as error:  # keep going; a crash is itself a finding
            errors.append((cfg.id, repr(error)))
            print(f"   ERROR {error!r}", flush=True)
            continue
        rows.append(row)
        print(f"   {row['solver_status']} -> {row['verdict']} "
              f"({row['seconds']} s, {row['n_rooms']} rooms)", flush=True)

    with open(out_dir / "summary.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "summary.md").write_text(rows_to_markdown(rows) + "\n")
    (out_dir / "environment.json").write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(), "ortools": ortools_version,
        "time_limit_seconds": args.time_limit, "num_search_workers": 1,
        "note": "Solver time limits are wall-clock, so results can vary between machines.",
        "gate_source": "legacy_projection (gates are drawn after solving; the solver has none)",
        "errors": errors,
    }, indent=2))
    print(f"\nWrote {len(rows)} layouts to {out_dir}; {len(errors)} errors.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
