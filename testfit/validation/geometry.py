"""Integer-centimeter geometry and the independent hard-constraint checks.

Everything here works from output coordinates only. Distances are converted to
whole centimeters so edge-contact tests are exact, matching the solver's 1 cm
grid without depending on floating-point tolerances.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from testfit.validation.snapshot import LayoutSnapshot, RectSpec

CM = 100
ATTACHED_MIN_CM = 50  # ATTACHED >= 0.5 m
ADJACENT_MIN_CM = 1  # ADJACENT: any positive shared edge
DOOR_MIN_CM = 90  # shared edge long enough to hold a door (~3 ft)
HARD_KINDS = {"ATTACHED", "ADJACENT"}
SOFT_KINDS = {"NEAR", "PREFERRED", "STACKED"}


def cm(value: float) -> int:
    return int(round(float(value) * CM))


@dataclass(frozen=True)
class Box:
    name: str
    x0: int
    y0: int
    x1: int
    y1: int
    f0: int
    f1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def length(self) -> int:
        return self.y1 - self.y0

    @property
    def area(self) -> int:
        return self.width * self.length

    def on_floor(self, floor: int) -> bool:
        return self.f0 <= floor <= self.f1

    def center2(self) -> tuple[int, int]:
        """Twice the center, to stay in integers."""
        return self.x0 + self.x1, self.y0 + self.y1


def to_box(rect: RectSpec) -> Box:
    last = rect.floor if rect.floor_end is None else rect.floor_end
    x0, y0 = cm(rect.x), cm(rect.y)
    return Box(
        rect.name,
        x0,
        y0,
        x0 + cm(rect.width),
        y0 + cm(rect.length),
        int(rect.floor),
        int(last),
    )


def overlap_dims(a: Box, b: Box) -> tuple[int, int]:
    return (
        min(a.x1, b.x1) - max(a.x0, b.x0),
        min(a.y1, b.y1) - max(a.y0, b.y0),
    )


def boxes_overlap(a: Box, b: Box) -> bool:
    dx, dy = overlap_dims(a, b)
    return dx > 0 and dy > 0


def shared_edge_cm(a: Box, b: Box) -> int:
    """Length of the coincident edge of two non-overlapping boxes (0 if none).

    Corner-only contact and gaps return 0.
    """
    if boxes_overlap(a, b):
        return 0
    best = 0
    if a.x1 == b.x0 or b.x1 == a.x0:
        best = max(best, min(a.y1, b.y1) - max(a.y0, b.y0))
    if a.y1 == b.y0 or b.y1 == a.y0:
        best = max(best, min(a.x1, b.x1) - max(a.x0, b.x0))
    return max(0, best)


def rect_gap_cm(a: Box, b: Box) -> int:
    """Rectilinear gap (sum of horizontal and vertical gaps), as in the solver."""
    dx = max(0, a.x0 - b.x1, b.x0 - a.x1)
    dy = max(0, a.y0 - b.y1, b.y0 - a.y1)
    return dx + dy


# ---------------------------------------------------------------- grid helpers


def _axes(boxes: Sequence[Box]) -> tuple[list[int], list[int]]:
    xs = sorted({v for b in boxes for v in (b.x0, b.x1)})
    ys = sorted({v for b in boxes for v in (b.y0, b.y1)})
    return xs, ys


def coverage_matrix(
    boxes: Iterable[Box], xs: list[int], ys: list[int]
) -> list[list[bool]]:
    matrix = [[False] * (len(xs) - 1) for _ in range(len(ys) - 1)]
    for b in boxes:
        i0, i1 = bisect_left(xs, b.x0), bisect_left(xs, b.x1)
        j0, j1 = bisect_left(ys, b.y0), bisect_left(ys, b.y1)
        for j in range(j0, j1):
            row = matrix[j]
            for i in range(i0, i1):
                row[i] = True
    return matrix


def union_area_cm2(boxes: Sequence[Box]) -> int:
    if not boxes:
        return 0
    xs, ys = _axes(boxes)
    matrix = coverage_matrix(boxes, xs, ys)
    return sum(
        (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
        for j, row in enumerate(matrix)
        for i, covered in enumerate(row)
        if covered
    )


def uncovered_area_cm2(upper: Sequence[Box], lower: Sequence[Box]) -> int:
    """Area covered by ``upper`` but not by ``lower``."""
    if not upper:
        return 0
    xs, ys = _axes([*upper, *lower])
    up = coverage_matrix(upper, xs, ys)
    low = coverage_matrix(lower, xs, ys)
    return sum(
        (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
        for j in range(len(ys) - 1)
        for i in range(len(xs) - 1)
        if up[j][i] and not low[j][i]
    )


def void_analysis(boxes: Sequence[Box]) -> dict:
    """Empty space inside the bounding box of ``boxes``.

    Returns exact void area, the largest connected void, and the largest empty
    axis-aligned rectangle (all in cm / cm^2).
    """
    if not boxes:
        return {
            "bbox_w": 0, "bbox_l": 0, "bbox_area": 0, "union_area": 0,
            "void_area": 0, "void_components": 0, "largest_void_area": 0,
            "largest_empty_rect_area": 0, "largest_empty_rect_dims": (0, 0),
        }
    xs, ys = _axes(boxes)
    matrix = coverage_matrix(boxes, xs, ys)
    rows, cols = len(ys) - 1, len(xs) - 1
    widths = [xs[i + 1] - xs[i] for i in range(cols)]
    heights = [ys[j + 1] - ys[j] for j in range(rows)]
    bbox_w, bbox_l = xs[-1] - xs[0], ys[-1] - ys[0]
    covered = sum(
        widths[i] * heights[j]
        for j in range(rows)
        for i in range(cols)
        if matrix[j][i]
    )
    void = bbox_w * bbox_l - covered

    seen = [[False] * cols for _ in range(rows)]
    components, largest = 0, 0
    for j in range(rows):
        for i in range(cols):
            if matrix[j][i] or seen[j][i]:
                continue
            components += 1
            area, stack = 0, [(j, i)]
            seen[j][i] = True
            while stack:
                cj, ci = stack.pop()
                area += widths[ci] * heights[cj]
                for nj, ni in ((cj + 1, ci), (cj - 1, ci), (cj, ci + 1), (cj, ci - 1)):
                    if 0 <= nj < rows and 0 <= ni < cols and not matrix[nj][ni] and not seen[nj][ni]:
                        seen[nj][ni] = True
                        stack.append((nj, ni))
            largest = max(largest, area)

    best_area, best_dims = 0, (0, 0)
    for top in range(rows):
        free = [True] * cols
        for bottom in range(top, rows):
            for i in range(cols):
                if matrix[bottom][i]:
                    free[i] = False
            height = ys[bottom + 1] - ys[top]
            run = 0
            for i in range(cols + 1):
                if i < cols and free[i]:
                    run += widths[i]
                else:
                    if run * height > best_area:
                        best_area, best_dims = run * height, (run, height)
                    run = 0
    return {
        "bbox_w": bbox_w, "bbox_l": bbox_l, "bbox_area": bbox_w * bbox_l,
        "union_area": covered, "void_area": void, "void_components": components,
        "largest_void_area": largest, "largest_empty_rect_area": best_area,
        "largest_empty_rect_dims": best_dims,
    }


# ------------------------------------------------------------ snapshot helpers


def room_boxes(snapshot: LayoutSnapshot) -> list[Box]:
    return [to_box(r) for r in snapshot.rooms]


def stair_boxes(snapshot: LayoutSnapshot) -> list[Box]:
    return [to_box(r) for r in snapshot.staircases]


def parking_box(snapshot: LayoutSnapshot) -> Box | None:
    if snapshot.parking is None:
        return None
    p = to_box(snapshot.parking)
    return Box(p.name, p.x0, p.y0, p.x1, p.y1, 0, 0)


def floor_boxes(snapshot: LayoutSnapshot, floor: int) -> list[Box]:
    """Rooms on ``floor`` plus any stair shaft serving it."""
    return [b for b in [*room_boxes(snapshot), *stair_boxes(snapshot)] if b.on_floor(floor)]


# ------------------------------------------------------------------ hard checks


@dataclass
class CheckResult:
    name: str
    passed: bool
    violations: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "violations": self.violations,
            "note": self.note,
        }


def _result(name: str, violations: list[str], note: str = "") -> CheckResult:
    return CheckResult(name, not violations, violations, note)


def check_finite_positive(s: LayoutSnapshot) -> CheckResult:
    bad = []
    for r in [*s.rooms, *s.staircases, *([s.parking] if s.parking else [])]:
        values = (r.x, r.y, r.width, r.length)
        if not all(math.isfinite(v) for v in values):
            bad.append(f"{r.name}: non-finite coordinate")
        elif r.width <= 0 or r.length <= 0:
            bad.append(f"{r.name}: non-positive size")
    names = [r.name for r in s.rooms]
    for name in sorted({n for n in names if names.count(n) > 1}):
        bad.append(f"{name}: duplicate room name")
    return _result("finite_positive_unique", bad)


def check_floor_range(s: LayoutSnapshot) -> CheckResult:
    bad = []
    if not 1 <= s.number_of_floors <= 5:
        bad.append(f"number_of_floors={s.number_of_floors} outside 1..5")
    for r in s.rooms:
        if not 1 <= r.floor <= s.number_of_floors or r.floor_end not in (None, r.floor):
            bad.append(f"{r.name}: floor {r.floor} outside 1..{s.number_of_floors}")
    for r in s.staircases:
        last = r.floor if r.floor_end is None else r.floor_end
        if r.floor < 1 or last > s.number_of_floors or last < r.floor:
            bad.append(f"{r.name}: floors {r.floor}..{last} outside 1..{s.number_of_floors}")
    return _result("floor_range_1_to_5", bad)


def check_no_overlap(s: LayoutSnapshot) -> CheckResult:
    bad = []
    boxes = [*room_boxes(s), *stair_boxes(s)]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            if max(a.f0, b.f0) <= min(a.f1, b.f1) and boxes_overlap(a, b):
                dx, dy = overlap_dims(a, b)
                bad.append(f"{a.name} overlaps {b.name} ({dx / CM:.2f} x {dy / CM:.2f} m)")
    return _result("no_overlap_rooms_and_stairs", bad)


def check_parking_overlap(s: LayoutSnapshot) -> CheckResult:
    """Parking must avoid every room and stair on every floor (solver rule)."""
    park = parking_box(s)
    bad = []
    if park is not None:
        for b in [*room_boxes(s), *stair_boxes(s)]:
            if boxes_overlap(park, b):
                bad.append(f"parking overlaps {b.name} (floor {b.f0})")
    return _result("parking_no_overlap", bad)


def check_containment(s: LayoutSnapshot) -> CheckResult:
    x0, y0, x1, y1 = (cm(v) for v in s.bounds)
    bad = []
    for b in [*room_boxes(s), *stair_boxes(s)]:
        if b.x0 < x0 or b.y0 < y0 or b.x1 > x1 or b.y1 > y1:
            bad.append(f"{b.name} leaves the buildable bounds")
    return _result("boundary_containment_buildable", bad)


def check_parking_in_site(s: LayoutSnapshot) -> CheckResult:
    park = parking_box(s)
    bad = []
    if park is not None and (
        park.x0 < 0 or park.y0 < 0 or park.x1 > cm(s.site_width) or park.y1 > cm(s.site_length)
    ):
        bad.append(f"{park.name} leaves the site")
    return _result("parking_inside_site", bad)


def check_relationships(s: LayoutSnapshot) -> list[CheckResult]:
    by_name = {r.name: to_box(r) for r in s.rooms}
    attached, adjacent, rules = [], [], []
    for room_a, room_b, raw_kind in s.relationships:
        kind = str(raw_kind).strip().upper()
        a, b = by_name.get(room_a), by_name.get(room_b)
        label = f"{room_a} {kind} {room_b}"
        if a is None or b is None:
            rules.append(f"{label}: room missing from layout")
            continue
        if kind == "STACKED":
            if abs(a.f0 - b.f0) != 1:
                rules.append(f"{label}: STACKED needs adjacent floors")
            continue
        if kind not in HARD_KINDS and kind not in SOFT_KINDS:
            rules.append(f"{label}: unknown relationship kind")
            continue
        if a.f0 != b.f0:
            rules.append(f"{label}: both rooms must be on the same floor")
            continue
        if kind not in HARD_KINDS:
            continue
        edge = shared_edge_cm(a, b)
        minimum = ATTACHED_MIN_CM if kind == "ATTACHED" else ADJACENT_MIN_CM
        if edge < minimum:
            message = f"{label}: shared edge {edge / CM:.2f} m < {minimum / CM:.2f} m"
            (attached if kind == "ATTACHED" else adjacent).append(message)
    return [
        _result("attached_min_0.5m", attached),
        _result("adjacent_positive_edge", adjacent),
        _result("relationship_floor_rules", rules),
    ]


def check_staircase(s: LayoutSnapshot) -> CheckResult:
    bad = []
    stairs = stair_boxes(s)
    n = s.number_of_floors
    if n == 1:
        if stairs:
            bad.append("single-floor building should not have a staircase shaft")
    else:
        for floor in range(1, n):
            if not any(b.f0 <= floor and floor + 1 <= b.f1 for b in stairs):
                bad.append(f"no stair connects floor {floor} to floor {floor + 1}")
        if s.expected_staircase is not None:
            w, l = cm(s.expected_staircase[0]), cm(s.expected_staircase[1])
            for b in stairs:
                if (b.width, b.length) != (w, l):
                    bad.append(
                        f"{b.name}: {b.width / CM:.2f} x {b.length / CM:.2f} m differs from requested"
                    )
    return _result("staircase_valid_continuous", bad)


def check_parking_valid(s: LayoutSnapshot) -> CheckResult:
    bad = []
    if s.parking is not None and s.expected_parking is not None:
        p = to_box(s.parking)
        if (p.width, p.length) != (cm(s.expected_parking[0]), cm(s.expected_parking[1])):
            bad.append(
                f"{p.name}: {p.width / CM:.2f} x {p.length / CM:.2f} m differs from requested"
            )
    return _result("parking_dimensions", bad)


def check_rooms_match_request(s: LayoutSnapshot) -> CheckResult:
    bad = []
    if s.expected_rooms is not None:
        placed = {r.name: r for r in s.rooms}
        for name, (w, l, floor) in s.expected_rooms.items():
            r = placed.get(name)
            if r is None:
                bad.append(f"{name}: requested room missing")
            elif (cm(r.width), cm(r.length), r.floor) != (cm(w), cm(l), floor):
                bad.append(f"{name}: size or floor differs from request")
        for name in placed.keys() - s.expected_rooms.keys():
            bad.append(f"{name}: room was not requested")
    return _result("rooms_match_request_fixed_size", bad)


def run_hard_checks(s: LayoutSnapshot) -> list[CheckResult]:
    return [
        check_finite_positive(s),
        check_floor_range(s),
        check_no_overlap(s),
        check_parking_overlap(s),
        check_containment(s),
        check_parking_in_site(s),
        *check_relationships(s),
        check_staircase(s),
        check_parking_valid(s),
        check_rooms_match_request(s),
    ]
