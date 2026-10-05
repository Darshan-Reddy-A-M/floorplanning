"""Constraint-based rectangular room placement using OR-Tools CP-SAT."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Sequence

from ortools.sat.python import cp_model


GRID_UNITS_PER_METER = 100
MINIMUM_POSITIVE_SHARED_EDGE_UNITS = 1
MIN_ATTACHED_EDGE = 0.5  # meters
MIN_ATTACHED_EDGE_UNITS = math.ceil(MIN_ATTACHED_EDGE * GRID_UNITS_PER_METER)


@dataclass(frozen=True)
class Room:
    """A rectangular room with dimensions expressed in meters."""

    name: str
    width: float
    length: float
    floor: int = 1


@dataclass(frozen=True)
class Placement:
    """A placed rectangle with coordinates and dimensions expressed in meters."""

    name: str
    x: float
    y: float
    width: float
    length: float
    floor: int = 1
    floor_end: int | None = None


@dataclass(frozen=True)
class RoomRelationship:
    """A hard or soft spatial relationship between two named rooms."""

    room_a: str
    room_b: str
    kind: str


@dataclass(frozen=True)
class LayoutResult:
    """CP-SAT status and the placements found, if the model is feasible."""

    status: str
    placements: list[Placement]
    message: str
    parking: Placement | None = None
    staircases: list[Placement] = field(default_factory=list)
    number_of_floors: int = 1
    parking_type: str = "No parking"
    road_access: str = "South"


@dataclass(frozen=True)
class LayoutMetrics:
    site_area: float
    total_room_area: float
    unused_area: float
    utilization_percent: float
    occupied_width: float
    occupied_length: float
    occupied_bbox_area: float
    layout_compactness_percent: float
    overlap_count: int
    boundary_violation_count: int
    attached_satisfied: int
    attached_total: int
    adjacent_satisfied: int
    adjacent_total: int
    near_satisfied: int
    near_total: int
    preferred_satisfied: int
    preferred_total: int
    near_distance_total: float
    preferred_penalty_total: float
    soft_penalty_distance_total: float
    relationship_satisfaction_percent: float
    number_of_floors: int = 1
    parking_area: float = 0.0
    building_footprint_area: float = 0.0
    total_allocated_site_area: float = 0.0
    site_utilization_percent: float = 0.0
    floor_room_area: dict[int, float] = field(default_factory=dict)
    floor_utilization_percent: dict[int, float] = field(default_factory=dict)
    staircase_area: float = 0.0
    stacked_satisfied: int = 0
    stacked_total: int = 0
    stacked_center_distance_total: float = 0.0


HARD_RELATIONSHIP_KINDS = {"ATTACHED", "ADJACENT"}
SOFT_RELATIONSHIP_KINDS = {"NEAR", "PREFERRED", "STACKED"}
RELATIONSHIP_KINDS = HARD_RELATIONSHIP_KINDS | SOFT_RELATIONSHIP_KINDS
SOFT_RELATIONSHIP_DISTANCE_THRESHOLD_M = 1.0
STACKED_DISTANCE_THRESHOLD_M = 1.0
MAX_BUILDING_FLOORS = 5
DEFAULT_STAIRCASE_WIDTH = 2.0
DEFAULT_STAIRCASE_LENGTH = 4.0
DEFAULT_PARKING_DIMENSIONS = {
    "1 car": (2.5, 5.0),
    "2 cars": (5.0, 5.0),
}
SOFT_RELATIONSHIP_DISTANCE_THRESHOLD_UNITS = round(
    SOFT_RELATIONSHIP_DISTANCE_THRESHOLD_M * GRID_UNITS_PER_METER
)
GEOMETRY_TOLERANCE = 1e-9


def _to_grid_units(value: float, label: str) -> int:
    """Convert meters to centimeters, rejecting non-finite and sub-centimeter values."""
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a finite number greater than zero.")
    units = round(number * GRID_UNITS_PER_METER)
    if units < 1:
        raise ValueError(f"{label} must be at least 0.01 m.")
    return int(units)


def _solve_single_floor_layout(
    site_width: float,
    site_length: float,
    rooms: Sequence[Room],
    time_limit_seconds: float = 5.0,
    relationships: Sequence[RoomRelationship] = (),
    buildable_bounds_units: tuple[int, int, int, int] | None = None,
) -> LayoutResult:
    """Find a hard-constraint-feasible layout, then optimize it in priority stages.

    All dimensions and distances use centimeter grid units. ATTACHED requires
    MIN_ATTACHED_EDGE meters of shared boundary; ADJACENT requires any positive-length
    shared edge. NEAR minimizes rectilinear gap, while PREFERRED penalizes the gap
    beyond the configured soft-distance threshold.
    """
    site_width_units = _to_grid_units(site_width, "Site width")
    site_length_units = _to_grid_units(site_length, "Site length")
    x_min, y_min, x_max, y_max = buildable_bounds_units or (
        0,
        0,
        site_width_units,
        site_length_units,
    )
    if not math.isfinite(time_limit_seconds) or time_limit_seconds <= 0:
        raise ValueError("The solver time limit must be greater than zero.")

    dimensions: list[tuple[int, int]] = []
    room_indices: dict[str, int] = {}
    for index, room in enumerate(rooms, start=1):
        if not room.name.strip():
            raise ValueError(f"Room {index} must have a name.")
        if room.name in room_indices:
            raise ValueError(f"Room names must be unique: {room.name!r}.")
        room_indices[room.name] = index - 1
        width_units = _to_grid_units(room.width, f"{room.name} width")
        length_units = _to_grid_units(room.length, f"{room.name} length")
        dimensions.append((width_units, length_units))

    validated_relationships: list[RoomRelationship] = []
    for index, relationship in enumerate(relationships, start=1):
        kind = relationship.kind.strip().upper()
        if kind not in RELATIONSHIP_KINDS:
            raise ValueError(
                f"Relationship {index} must be ATTACHED, ADJACENT, NEAR, or PREFERRED."
            )
        if relationship.room_a == relationship.room_b:
            raise ValueError(f"Relationship {index} must refer to two different rooms.")
        if relationship.room_a not in room_indices or relationship.room_b not in room_indices:
            raise ValueError(
                f"Relationship {index} refers to a room that is not in the room list."
            )
        validated_relationships.append(
            RoomRelationship(relationship.room_a, relationship.room_b, kind)
        )

    model = cp_model.CpModel()
    x_positions: list[cp_model.IntVar] = []
    y_positions: list[cp_model.IntVar] = []
    x_intervals = []
    y_intervals = []

    for index, (width_units, length_units) in enumerate(dimensions):
        x = model.new_int_var(x_min, x_max - width_units, f"x_{index}")
        y = model.new_int_var(y_min, y_max - length_units, f"y_{index}")
        model.add(x + width_units <= x_max)
        model.add(y + length_units <= y_max)
        x_positions.append(x)
        y_positions.append(y)
        x_intervals.append(model.new_fixed_size_interval_var(x, width_units, f"x_interval_{index}"))
        y_intervals.append(model.new_fixed_size_interval_var(y, length_units, f"y_interval_{index}"))

    if dimensions:
        model.add_no_overlap_2d(x_intervals, y_intervals)

    near_distances: list[cp_model.IntVar] = []
    preferred_penalties: list[cp_model.IntVar] = []
    for relationship_index, relationship in enumerate(validated_relationships):
        first_index = room_indices[relationship.room_a]
        second_index = room_indices[relationship.room_b]
        first_width, first_length = dimensions[first_index]
        second_width, second_length = dimensions[second_index]

        if relationship.kind in HARD_RELATIONSHIP_KINDS:
            minimum_shared_edge_units = (
                MIN_ATTACHED_EDGE_UNITS
                if relationship.kind == "ATTACHED"
                else MINIMUM_POSITIVE_SHARED_EDGE_UNITS
            )
            _add_hard_edge_touch_constraint(
                model,
                relationship_index,
                first_index,
                second_index,
                first_width,
                first_length,
                second_width,
                second_length,
                x_positions,
                y_positions,
                minimum_shared_edge_units,
            )
            continue

        max_distance = site_width_units + site_length_units
        horizontal_gap = model.new_int_var(
            0, site_width_units, f"rel_{relationship_index}_horizontal_gap"
        )
        vertical_gap = model.new_int_var(
            0, site_length_units, f"rel_{relationship_index}_vertical_gap"
        )
        model.add_max_equality(
            horizontal_gap,
            [
                0,
                x_positions[first_index]
                - (x_positions[second_index] + second_width),
                x_positions[second_index]
                - (x_positions[first_index] + first_width),
            ],
        )
        model.add_max_equality(
            vertical_gap,
            [
                0,
                y_positions[first_index]
                - (y_positions[second_index] + second_length),
                y_positions[second_index]
                - (y_positions[first_index] + first_length),
            ],
        )
        distance = model.new_int_var(
            0, max_distance, f"rel_{relationship_index}_distance"
        )
        model.add(distance == horizontal_gap + vertical_gap)

        if relationship.kind == "NEAR":
            near_distances.append(distance)
        else:
            preferred_penalty = model.new_int_var(
                0,
                max(0, max_distance - SOFT_RELATIONSHIP_DISTANCE_THRESHOLD_UNITS),
                f"rel_{relationship_index}_preferred_penalty",
            )
            model.add_max_equality(
                preferred_penalty,
                [0, distance - SOFT_RELATIONSHIP_DISTANCE_THRESHOLD_UNITS],
            )
            preferred_penalties.append(preferred_penalty)

    # Fixed room areas make site-wide unused area constant. Optimize the explicit
    # bounding rectangle around the rooms, independent of its offset from the origin.
    occupied_left = model.new_int_var(0, site_width_units, "occupied_left")
    occupied_right = model.new_int_var(0, site_width_units, "occupied_right")
    occupied_bottom = model.new_int_var(0, site_length_units, "occupied_bottom")
    occupied_top = model.new_int_var(0, site_length_units, "occupied_top")
    occupied_width = model.new_int_var(0, site_width_units, "occupied_width")
    occupied_length = model.new_int_var(0, site_length_units, "occupied_length")
    if dimensions:
        model.add_min_equality(occupied_left, x_positions)
        model.add_max_equality(
            occupied_right,
            [
                x_positions[index] + dimensions[index][0]
                for index in range(len(dimensions))
            ],
        )
        model.add_min_equality(occupied_bottom, y_positions)
        model.add_max_equality(
            occupied_top,
            [
                y_positions[index] + dimensions[index][1]
                for index in range(len(dimensions))
            ],
        )
        model.add(occupied_width == occupied_right - occupied_left)
        model.add(occupied_length == occupied_top - occupied_bottom)
    else:
        model.add(occupied_left == 0)
        model.add(occupied_right == 0)
        model.add(occupied_bottom == 0)
        model.add(occupied_top == 0)
        model.add(occupied_width == 0)
        model.add(occupied_length == 0)
    occupied_bbox_area = model.new_int_var(
        0, site_width_units * site_length_units, "occupied_bbox_area"
    )
    model.add_multiplication_equality(
        occupied_bbox_area, [occupied_width, occupied_length]
    )

    objective_stages = [("occupied bounding-box area", occupied_bbox_area)]
    if dimensions:
        objective_stages.append(
            ("occupied bounding-box dimensions", occupied_width + occupied_length)
        )
    if near_distances:
        objective_stages.append(("NEAR distance", sum(near_distances)))
    if preferred_penalties:
        objective_stages.append(("PREFERRED penalty", sum(preferred_penalties)))
    if x_positions or y_positions:
        objective_stages.append(
            ("lower-left compactness", sum(x_positions) + sum(y_positions))
        )

    # Solve sequentially and pin each proven optimum before moving to the next
    # soft objective. The shared time budget only affects optimization quality;
    # hard constraints remain in the model for every solve.
    start_time = time.monotonic()
    last_solver: cp_model.CpSolver | None = None
    all_stages_optimal = True
    for stage_index, (stage_name, objective) in enumerate(objective_stages):
        remaining_seconds = time_limit_seconds - (time.monotonic() - start_time)
        if remaining_seconds <= 0.01:
            all_stages_optimal = False
            break

        model.minimize(objective)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = remaining_seconds
        solver.parameters.num_search_workers = 1
        status_code = solver.solve(model)
        if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if last_solver is None:
                status = solver.status_name(status_code)
                return LayoutResult(
                    status=status,
                    placements=[],
                    message="CP-SAT did not find a feasible arrangement.",
                )
            all_stages_optimal = False
            break

        last_solver = solver
        if status_code != cp_model.OPTIMAL:
            all_stages_optimal = False
            break

        if stage_index < len(objective_stages) - 1:
            model.add(objective == solver.value(objective))

    if last_solver is None:
        return LayoutResult(
            status="UNKNOWN",
            placements=[],
            message="CP-SAT did not return a feasible arrangement within the time limit.",
        )

    status = (
        "OPTIMAL"
        if all_stages_optimal
        else "FEASIBLE"
    )
    placements = [
        Placement(
            name=room.name,
            x=last_solver.value(x_positions[index]) / GRID_UNITS_PER_METER,
            y=last_solver.value(y_positions[index]) / GRID_UNITS_PER_METER,
            width=dimensions[index][0] / GRID_UNITS_PER_METER,
            length=dimensions[index][1] / GRID_UNITS_PER_METER,
        )
        for index, room in enumerate(rooms)
    ]
    message = (
        "All objective stages were optimized."
        if status == "OPTIMAL"
        else "A feasible layout was found; some objective stages were not proven optimal before the time limit."
    )
    return LayoutResult(status=status, placements=placements, message=message)


def solve_layout(
    site_width: float,
    site_length: float,
    rooms: Sequence[Room],
    time_limit_seconds: float = 5.0,
    relationships: Sequence[RoomRelationship] = (),
    *,
    number_of_floors: int = 1,
    parking_type: str = "No parking",
    parking_width: float | None = None,
    parking_length: float | None = None,
    road_access: str = "South",
    staircase_width: float = DEFAULT_STAIRCASE_WIDTH,
    staircase_length: float = DEFAULT_STAIRCASE_LENGTH,
    buildable_bounds: tuple[float, float, float, float] | None = None,
) -> LayoutResult:
    """Solve a single-floor or multi-floor building layout with optional parking."""
    from testfit.v4_optimizer import solve_building_layout

    return solve_building_layout(
        site_width=site_width,
        site_length=site_length,
        rooms=rooms,
        time_limit_seconds=time_limit_seconds,
        relationships=relationships,
        number_of_floors=number_of_floors,
        parking_type=parking_type,
        parking_width=parking_width,
        parking_length=parking_length,
        road_access=road_access,
        staircase_width=staircase_width,
        staircase_length=staircase_length,
        buildable_bounds=buildable_bounds,
    )


def _add_hard_edge_touch_constraint(
    model: cp_model.CpModel,
    relationship_index: int,
    first_index: int,
    second_index: int,
    first_width: int,
    first_length: int,
    second_width: int,
    second_length: int,
    x_positions: Sequence[cp_model.IntVar],
    y_positions: Sequence[cp_model.IntVar],
    minimum_shared_edge_units: int,
) -> None:
    """Require one shared edge whose overlap meets the requested grid-unit minimum."""
    first_left_of_second = model.new_bool_var(f"rel_{relationship_index}_a_left")
    second_left_of_first = model.new_bool_var(f"rel_{relationship_index}_b_left")
    first_below_second = model.new_bool_var(f"rel_{relationship_index}_a_below")
    second_below_first = model.new_bool_var(f"rel_{relationship_index}_b_below")
    touching_sides = [
        first_left_of_second,
        second_left_of_first,
        first_below_second,
        second_below_first,
    ]
    model.add(sum(touching_sides) == 1)

    model.add(
        x_positions[first_index] + first_width == x_positions[second_index]
    ).only_enforce_if(first_left_of_second)
    model.add(
        y_positions[first_index]
        <= y_positions[second_index]
        + second_length
        - minimum_shared_edge_units
    ).only_enforce_if(first_left_of_second)
    model.add(
        y_positions[second_index]
        <= y_positions[first_index]
        + first_length
        - minimum_shared_edge_units
    ).only_enforce_if(first_left_of_second)

    model.add(
        x_positions[second_index] + second_width == x_positions[first_index]
    ).only_enforce_if(second_left_of_first)
    model.add(
        y_positions[first_index]
        <= y_positions[second_index]
        + second_length
        - minimum_shared_edge_units
    ).only_enforce_if(second_left_of_first)
    model.add(
        y_positions[second_index]
        <= y_positions[first_index]
        + first_length
        - minimum_shared_edge_units
    ).only_enforce_if(second_left_of_first)

    model.add(
        y_positions[first_index] + first_length == y_positions[second_index]
    ).only_enforce_if(first_below_second)
    model.add(
        x_positions[first_index]
        <= x_positions[second_index]
        + second_width
        - minimum_shared_edge_units
    ).only_enforce_if(first_below_second)
    model.add(
        x_positions[second_index]
        <= x_positions[first_index]
        + first_width
        - minimum_shared_edge_units
    ).only_enforce_if(first_below_second)

    model.add(
        y_positions[second_index] + second_length == y_positions[first_index]
    ).only_enforce_if(second_below_first)
    model.add(
        x_positions[first_index]
        <= x_positions[second_index]
        + second_width
        - minimum_shared_edge_units
    ).only_enforce_if(second_below_first)
    model.add(
        x_positions[second_index]
        <= x_positions[first_index]
        + first_width
        - minimum_shared_edge_units
    ).only_enforce_if(second_below_first)


def calculate_metrics(
    site_width: float,
    site_length: float,
    placements: Sequence[Placement],
    relationships: Sequence[RoomRelationship] = (),
    *,
    number_of_floors: int | None = None,
    parking: Placement | None = None,
    staircases: Sequence[Placement] = (),
) -> LayoutMetrics:
    """Audit room geometry and calculate per-floor and site-level metrics."""
    site_area = float(site_width) * float(site_length)
    total_room_area = sum(room.width * room.length for room in placements)
    highest_floor = max(
        [
            1,
            *(room.floor for room in placements),
            *(stair.floor_end or stair.floor for stair in staircases),
        ]
    )
    floor_count = highest_floor if number_of_floors is None else number_of_floors
    floor_room_area = {
        floor: sum(
            room.width * room.length for room in placements if room.floor == floor
        )
        for floor in range(1, floor_count + 1)
    }
    floor_bbox_dimensions: dict[int, tuple[float, float]] = {}
    for floor in range(1, floor_count + 1):
        floor_rooms = [room for room in placements if room.floor == floor]
        if floor_rooms:
            floor_bbox_dimensions[floor] = (
                max(room.x + room.width for room in floor_rooms)
                - min(room.x for room in floor_rooms),
                max(room.y + room.length for room in floor_rooms)
                - min(room.y for room in floor_rooms),
            )
        else:
            floor_bbox_dimensions[floor] = (0.0, 0.0)
    occupied_width = max(
        (width for width, _ in floor_bbox_dimensions.values()), default=0.0
    )
    occupied_length = max(
        (length for _, length in floor_bbox_dimensions.values()), default=0.0
    )
    occupied_bbox_area = sum(
        width * length for width, length in floor_bbox_dimensions.values()
    )

    layout_compactness = (
        total_room_area / occupied_bbox_area * 100
        if occupied_bbox_area > 0
        else 0.0
    )
    overlap_count = 0
    boundary_violation_count = 0
    placement_by_name = {placement.name: placement for placement in placements}
    building_shapes = [*placements, *staircases]

    for room in [*building_shapes, *([parking] if parking is not None else [])]:
        if (
            room.x < -GEOMETRY_TOLERANCE
            or room.y < -GEOMETRY_TOLERANCE
            or room.x + room.width > site_width + GEOMETRY_TOLERANCE
            or room.y + room.length > site_length + GEOMETRY_TOLERANCE
        ):
            boundary_violation_count += 1

    for index, first in enumerate(building_shapes):
        for second in building_shapes[index + 1 :]:
            if _share_floor(first, second) and _rectangles_overlap(first, second):
                overlap_count += 1
    if parking is not None:
        for shape in building_shapes:
            if _rectangles_overlap(parking, shape):
                overlap_count += 1

    attached_total = attached_satisfied = 0
    adjacent_total = adjacent_satisfied = 0
    near_total = near_satisfied = 0
    preferred_total = preferred_satisfied = 0
    stacked_total = stacked_satisfied = 0
    near_distance_total = 0.0
    preferred_penalty_total = 0.0
    stacked_center_distance_total = 0.0
    all_relationships_satisfied = 0

    for relationship in relationships:
        kind = relationship.kind.strip().upper()
        if kind not in RELATIONSHIP_KINDS:
            raise ValueError(
                "Relationship kind must be ATTACHED, ADJACENT, NEAR, PREFERRED, or STACKED."
            )

        first = placement_by_name.get(relationship.room_a)
        second = placement_by_name.get(relationship.room_b)
        if kind in HARD_RELATIONSHIP_KINDS:
            satisfied = (
                first is not None
                and second is not None
                and first.floor == second.floor
                and not _rectangles_overlap(first, second)
                and _share_boundary(
                    first,
                    second,
                    MIN_ATTACHED_EDGE if kind == "ATTACHED" else 0.0,
                )
            )
            if kind == "ATTACHED":
                attached_total += 1
                attached_satisfied += int(satisfied)
            else:
                adjacent_total += 1
                adjacent_satisfied += int(satisfied)
        elif kind in {"NEAR", "PREFERRED"}:
            distance = (
                rectilinear_distance(first, second)
                if (
                    first is not None
                    and second is not None
                    and first.floor == second.floor
                )
                else math.inf
            )
            satisfied = (
                distance
                <= SOFT_RELATIONSHIP_DISTANCE_THRESHOLD_M + GEOMETRY_TOLERANCE
            )
            if kind == "NEAR":
                near_total += 1
                near_satisfied += int(satisfied)
                if math.isfinite(distance):
                    near_distance_total += distance
            else:
                preferred_total += 1
                preferred_satisfied += int(satisfied)
                if math.isfinite(distance):
                    preferred_penalty_total += max(
                        0.0, distance - SOFT_RELATIONSHIP_DISTANCE_THRESHOLD_M
                    )
        else:
            stacked_total += 1
            distance = (
                _center_distance(first, second)
                if (
                    first is not None
                    and second is not None
                    and abs(first.floor - second.floor) == 1
                )
                else math.inf
            )
            satisfied = (
                distance <= STACKED_DISTANCE_THRESHOLD_M + GEOMETRY_TOLERANCE
            )
            stacked_satisfied += int(satisfied)
            if math.isfinite(distance):
                stacked_center_distance_total += distance
        all_relationships_satisfied += int(satisfied)

    relationship_total = (
        attached_total
        + adjacent_total
        + near_total
        + preferred_total
        + stacked_total
    )
    relationship_satisfaction = (
        all_relationships_satisfied / relationship_total * 100
        if relationship_total
        else 100.0
    )
    utilization = (total_room_area / site_area * 100) if site_area > 0 else 0.0
    parking_area = parking.width * parking.length if parking is not None else 0.0
    staircase_area = sum(stair.width * stair.length for stair in staircases)
    building_footprint_area = _rectangle_union_area(building_shapes)
    total_allocated_site_area = _rectangle_union_area(
        [*building_shapes, *([parking] if parking is not None else [])]
    )
    floor_utilization = {
        floor: area / site_area * 100 if site_area > 0 else 0.0
        for floor, area in floor_room_area.items()
    }
    return LayoutMetrics(
        site_area=site_area,
        total_room_area=total_room_area,
        unused_area=site_area - total_allocated_site_area,
        utilization_percent=utilization,
        occupied_width=occupied_width,
        occupied_length=occupied_length,
        occupied_bbox_area=occupied_bbox_area,
        layout_compactness_percent=layout_compactness,
        overlap_count=overlap_count,
        boundary_violation_count=boundary_violation_count,
        attached_satisfied=attached_satisfied,
        attached_total=attached_total,
        adjacent_satisfied=adjacent_satisfied,
        adjacent_total=adjacent_total,
        near_satisfied=near_satisfied,
        near_total=near_total,
        preferred_satisfied=preferred_satisfied,
        preferred_total=preferred_total,
        near_distance_total=near_distance_total,
        preferred_penalty_total=preferred_penalty_total,
        soft_penalty_distance_total=(
            near_distance_total
            + preferred_penalty_total
            + stacked_center_distance_total
        ),
        relationship_satisfaction_percent=relationship_satisfaction,
        number_of_floors=floor_count,
        parking_area=parking_area,
        building_footprint_area=building_footprint_area,
        total_allocated_site_area=total_allocated_site_area,
        site_utilization_percent=(
            total_allocated_site_area / site_area * 100 if site_area > 0 else 0.0
        ),
        floor_room_area=floor_room_area,
        floor_utilization_percent=floor_utilization,
        staircase_area=staircase_area,
        stacked_satisfied=stacked_satisfied,
        stacked_total=stacked_total,
        stacked_center_distance_total=stacked_center_distance_total,
    )


def _share_floor(first: Placement, second: Placement) -> bool:
    first_end = first.floor_end if first.floor_end is not None else first.floor
    second_end = second.floor_end if second.floor_end is not None else second.floor
    return max(first.floor, second.floor) <= min(first_end, second_end)


def _center_distance(first: Placement, second: Placement) -> float:
    return abs(
        first.x + first.width / 2 - second.x - second.width / 2
    ) + abs(first.y + first.length / 2 - second.y - second.length / 2)


def _rectangle_union_area(rectangles: Sequence[Placement]) -> float:
    """Return the 2D union area of a collection of axis-aligned footprints."""
    if not rectangles:
        return 0.0
    x_edges = sorted(
        {edge for rectangle in rectangles for edge in (rectangle.x, rectangle.x + rectangle.width)}
    )
    union_area = 0.0
    for left, right in zip(x_edges, x_edges[1:]):
        if right - left <= GEOMETRY_TOLERANCE:
            continue
        spans = sorted(
            (
                rectangle.y,
                rectangle.y + rectangle.length,
            )
            for rectangle in rectangles
            if rectangle.x < right - GEOMETRY_TOLERANCE
            and rectangle.x + rectangle.width > left + GEOMETRY_TOLERANCE
        )
        covered_length = 0.0
        span_start = span_end = None
        for start, end in spans:
            if span_start is None:
                span_start, span_end = start, end
            elif start <= span_end + GEOMETRY_TOLERANCE:
                span_end = max(span_end, end)
            else:
                covered_length += span_end - span_start
                span_start, span_end = start, end
        if span_start is not None:
            covered_length += span_end - span_start
        union_area += (right - left) * covered_length
    return union_area


def rectilinear_distance(first: Placement, second: Placement) -> float:
    """Return the minimum rectilinear gap between two room rectangles in meters."""
    if first.floor != second.floor:
        return math.inf
    horizontal_gap = max(
        0.0,
        first.x - (second.x + second.width),
        second.x - (first.x + first.width),
    )
    vertical_gap = max(
        0.0,
        first.y - (second.y + second.length),
        second.y - (first.y + first.length),
    )
    return horizontal_gap + vertical_gap


def _rectangles_overlap(first: Placement, second: Placement) -> bool:
    """Return true only when the rectangles share positive area."""
    overlap_width = min(first.x + first.width, second.x + second.width) - max(
        first.x, second.x
    )
    overlap_length = min(first.y + first.length, second.y + second.length) - max(
        first.y, second.y
    )
    return (
        overlap_width > GEOMETRY_TOLERANCE
        and overlap_length > GEOMETRY_TOLERANCE
    )


def _intervals_overlap(
    first_start: float,
    first_length: float,
    second_start: float,
    second_length: float,
    minimum_shared_length: float = 0.0,
) -> bool:
    """Require positive overlap and, when set, meet the minimum shared length."""
    shared_length = (
        min(first_start + first_length, second_start + second_length)
        - max(first_start, second_start)
    )
    return (
        shared_length > GEOMETRY_TOLERANCE
        and shared_length + GEOMETRY_TOLERANCE >= minimum_shared_length
    )


def _share_boundary(
    first: Placement, second: Placement, minimum_shared_length: float = 0.0
) -> bool:
    """Return true for coincident edges whose shared span meets the minimum."""
    vertical_boundary = (
        math.isclose(
            first.x + first.width,
            second.x,
            rel_tol=0.0,
            abs_tol=GEOMETRY_TOLERANCE,
        )
        or math.isclose(
            second.x + second.width,
            first.x,
            rel_tol=0.0,
            abs_tol=GEOMETRY_TOLERANCE,
        )
    ) and _intervals_overlap(
        first.y,
        first.length,
        second.y,
        second.length,
        minimum_shared_length,
    )

    horizontal_boundary = (
        math.isclose(
            first.y + first.length,
            second.y,
            rel_tol=0.0,
            abs_tol=GEOMETRY_TOLERANCE,
        )
        or math.isclose(
            second.y + second.length,
            first.y,
            rel_tol=0.0,
            abs_tol=GEOMETRY_TOLERANCE,
        )
    ) and _intervals_overlap(
        first.x,
        first.width,
        second.x,
        second.width,
        minimum_shared_length,
    )

    return vertical_boundary or horizontal_boundary