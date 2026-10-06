"""Independent, OR-Tools-free validation of generated layouts.

Everything in this package works from output coordinates only, so saved
layouts can be re-validated anywhere and results never depend on solver
variables or UI metrics.
"""

from testfit.validation.geometry import CheckResult, run_hard_checks
from testfit.validation.legacy_gates import legacy_gate_points
from testfit.validation.quality import classify_room, compute_quality
from testfit.validation.report import (
    SUMMARY_COLUMNS,
    build_scorecard,
    evaluate,
    format_text,
    rows_to_markdown,
    summary_row,
    to_json,
)
from testfit.validation.snapshot import (
    LayoutSnapshot,
    RectSpec,
    as_rect,
    snapshot_from_layout,
)

__all__ = [
    "SUMMARY_COLUMNS", "rows_to_markdown", "summary_row",
    "CheckResult", "LayoutSnapshot", "RectSpec", "as_rect", "build_scorecard",
    "classify_room", "compute_quality", "evaluate", "format_text",
    "legacy_gate_points", "run_hard_checks", "snapshot_from_layout", "to_json",
]
