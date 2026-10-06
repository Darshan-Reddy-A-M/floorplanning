#!/usr/bin/env python
"""Re-validate saved layouts without OR-Tools (no solving happens here).

Accepts JSON files written by generate_samples.py (or a directory of them) and
re-runs the validator, e.g. after thresholds change.

    python scripts/validate_snapshot.py reports/baseline
    python scripts/validate_snapshot.py reports/baseline/sf_2f_40x60_south_1car.json --write
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from testfit.validation.report import (  # noqa: E402
    evaluate, format_text, rows_to_markdown, summary_row,
)
from testfit.validation.snapshot import LayoutSnapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--write", action="store_true", help="store the new report in each file")
    args = parser.parse_args()

    files: list[pathlib.Path] = []
    for raw in args.paths:
        path = pathlib.Path(raw)
        files += sorted(path.glob("*.json")) if path.is_dir() else [path]
    rows = []
    for file in files:
        data = json.loads(file.read_text())
        if "snapshot" not in data:
            continue
        snapshot = LayoutSnapshot.from_dict(data["snapshot"])
        report = evaluate(snapshot, data.get("config", {}).get("id", file.stem))
        print(format_text(report))
        rows.append(summary_row(report, data.get("solver", {}).get("seconds"), len(snapshot.rooms)))
        if args.write:
            data["report"] = report
            file.write_text(json.dumps(data, indent=2, default=str))
    print()
    print(rows_to_markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
