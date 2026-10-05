"""Floor-aware CP-SAT layout solving with parking and stair footprints."""

from __future__ import annotations

import math
import time
from typing import Sequence

from ortools.sat.python import cp_model

from testfit.optimizer import (
    DEFAULT_PARKING_DIMENSIONS,
    DEFAULT_STAIRCASE_LENGTH,
    DEFAULT_STAIRCASE_WIDTH,
    GRID_UNITS_PER_METER,
    HARD_RELATIONSHIP_KINDS,
    MIN_ATTACHED_EDGE_UNITS,
    MINIMUM_POSITIVE_SHARED_EDGE_UNITS,
    RELATIONSHIP_KINDS,
    SOFT_RELATIONSHIP_DISTANCE_THRESHOLD_UNITS,
    Room,
    RoomRelationship,
    Placement,
    LayoutResult,
    _add_hard_edge_touch_constraint,
    _solve_single_floor_layout,
    _to_grid_units,
)

ROAD_ACCESS_SIDES = {"North", "South", "East", "West"}
PARKING_TYPES = {"No parking", *DEFAULT_PARKING_DIMENSIONS}


def _canonical_parking_type(value: str) -> str:
    labels = {parking_type.casefold(): parking_type for parking_type in PARKING_TYPES}
    labels["none"] = "No parking"
    labels["no parking"] = "No parking"
    try:
        return labels[str(value).strip().casefold()]
    except KeyError as error:
        raise ValueError("Parking must be No parking, 1 car, or 2 cars.") from error


def solve_building_layout(
    *,
    site_width: float,
    site_length: float,
    rooms: Sequence[Room],
    time_limit_seconds: float,
    relationships: Sequence[RoomRelationship],
    number_of_floors: int,
    parking_type: str,
    parking_width: float | None,
    parking_length: float | None,
    road_access: str,
    staircase_width: float,
    staircase_length: float,
    buildable_bounds: tuple[float, float, float, float] | None = None,
) -> LayoutResult:
    """Validate building inputs and solve the corresponding floor-aware model."""
    if (
        isinstance(number_of_floors, bool)
        or not isinstance(number_of_floors, int)
        or number_of_floors not in (1, 2, 3, 4, 5)
    ):
        raise ValueError("Number of floors must be between 1 and 5.")
    if not math.isfinite(time_limit_seconds) or time_limit_seconds <= 0:
        raise ValueError("The solver time limit must be greater than zero.")

    site_width_units = _to_grid_units(site_width, "Site width")
    site_length_units = _to_grid_units(site_length, "Site length")
    if buildable_bounds is None:
        buildable_bounds_units = (0, 0, site_width_units, site_length_units)
    else:
        if len(buildable_bounds) != 4:
            raise ValueError("Buildable bounds must be (left, bottom, right, top).")
        bounds = tuple(float(value) for value in buildable_bounds)
        if not all(math.isfinite(value) for value in bounds):
            raise ValueError("Buildable bounds must be finite.")
        x_min_m, y_min_m, x_max_m, y_max_m = bounds
        if (
            x_min_m < 0
            or y_min_m < 0
            or x_max_m > site_width
            or y_max_m > site_length
            or x_min_m >= x_max_m
            or y_min_m >= y_max_m
        ):
            raise ValueError("Setbacks must leave a positive buildable area inside the site.")
        buildable_bounds_units = tuple(
            round(value * GRID_UNITS_PER_METER) for value in bounds
        )
    parking_type = _canonical_parking_type(parking_type)
    normalized_road = str(road_access).strip().title()
    if normalized_road not in ROAD_ACCESS_SIDES:
        raise ValueError("Road / Site Access must be North, South, East, or West.")

    normalized_rooms: list[Room] = []
    room_indices: dict[str, int] = {}
    room_floors: dict[str, int] = {}
    dimensions: list[tuple[int, int]] = []
    for index, room in enumerate(rooms, start=1):
        if not room.name.strip():
            raise ValueError(f"Room {index} must have a name.")
        if room.name in room_indices:
            raise ValueError(f"Room names must be unique: {room.name!r}.")
        if isinstance(room.floor, bool):
            raise ValueError(f"{room.name} floor must be an integer from 1 to {number_of_floors}.")
        try:
            floor = int(room.floor)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(
                f"{room.name} floor must be an integer from 1 to {number_of_floors}."
            ) from error
        if floor != room.floor or floor < 1 or floor > number_of_floors:
            raise ValueError(
                f"{room.name} floor must be between 1 and {number_of_floors}."
            )
        room_indices[room.name] = index - 1
        room_floors[room.name] = floor
        normalized_rooms.append(Room(room.name, room.width, room.length, floor))
        dimensions.append(
            (
                _to_grid_units(room.width, f"{room.name} width"),
                _to_grid_units(room.length, f"{room.name} length"),
            )
        )

    validated_relationships: list[RoomRelationship] = []
    for index, relationship in enumerate(relationships, start=1):
        kind = relationship.kind.strip().upper()
        if kind not in RELATIONSHIP_KINDS:
            allowed = ", ".join(sorted(RELATIONSHIP_KINDS))
            raise ValueError(f"Relationship {index} must be one of: {allowed}.")
        if relationship.room_a == relationship.room_b:
            raise ValueError(f"Relationship {index} must refer to two different rooms.")
        if relationship.room_a not in room_indices or relationship.room_b not in room_indices:
            raise ValueError(
                f"Relationship {index} refers to a room that is not in the room list."
            )
        first_floor = room_floors[relationship.room_a]
        second_floor = room_floors[relationship.room_b]
        if kind == "STACKED":
            if abs(first_floor - second_floor) != 1:
                raise ValueError(
                    f"Relationship {index} STACKED must connect rooms on adjacent floors."
                )
        elif first_floor != second_floor:
            raise ValueError(
                f"Relationship {index} {kind} requires both rooms to be on the same floor."
            )
        validated_relationships.append(
            RoomRelationship(relationship.room_a, relationship.room_b, kind)
        )

    parking_dimensions: tuple[int, int] | None = None
    if parking_type != "No parking":
        default_width, default_length = DEFAULT_PARKING_DIMENSIONS[parking_type]
        parking_dimensions = (
            _to_grid_units(
                default_width if parking_width is None else parking_width,
                "Parking width",
            ),
            _to_grid_units(
                default_length if parking_length is None else parking_length,
                "Parking length",
            ),
        )

    staircase_dimensions: tuple[int, int] | None = None
    if number_of_floors > 1:
        staircase_dimensions = (
            _to_grid_units(staircase_width, "Staircase width"),
            _to_grid_units(staircase_length, "Staircase length"),
        )

    buildable_width_units = buildable_bounds_units[2] - buildable_bounds_units[0]
    buildable_length_units = buildable_bounds_units[3] - buildable_bounds_units[1]
    oversized_room = next(
        (
            normalized_rooms[index].name
            for index, (width, length) in enumerate(dimensions)
            if width > buildable_width_units or length > buildable_length_units
        ),
        None,
    )
    if oversized_room is not None:
        return LayoutResult(
            status="INFEASIBLE",
            placements=[],
            message=f"{oversized_room} is larger than the buildable area after setbacks.",
            number_of_floors=number_of_floors,
            parking_type=parking_type,
            road_access=normalized_road,
        )
    if staircase_dimensions is not None and (
        staircase_dimensions[0] > buildable_width_units
        or staircase_dimensions[1] > buildable_length_units
    ):
        return LayoutResult(
            status="INFEASIBLE",
            placements=[],
            message="The staircase is larger than the buildable area after setbacks.",
            number_of_floors=number_of_floors,
            parking_type=parking_type,
            road_access=normalized_road,
        )

    if (
        number_of_floors == 1
        and parking_dimensions is None
        and all(room.floor == 1 for room in normalized_rooms)
        and all(item.kind != "STACKED" for item in validated_relationships)
    ):
        legacy_result = _solve_single_floor_layout(
            site_width,
            site_length,
            normalized_rooms,
            time_limit_seconds,
            validated_relationships,
            buildable_bounds_units=buildable_bounds_units,
        )
        return LayoutResult(
            status=legacy_result.status,
            placements=legacy_result.placements,
            message=legacy_result.message,
            number_of_floors=1,
            parking_type=parking_type,
            road_access=normalized_road,
        )

    return _solve_floor_aware_model(
        site_width_units=site_width_units,
        site_length_units=site_length_units,
        rooms=normalized_rooms,
        dimensions=dimensions,
        room_indices=room_indices,
        time_limit_seconds=time_limit_seconds,
        relationships=validated_relationships,
        number_of_floors=number_of_floors,
        parking_type=parking_type,
        parking_dimensions=parking_dimensions,
        road_access=normalized_road,
        staircase_dimensions=staircase_dimensions,
        buildable_bounds_units=buildable_bounds_units,
    )


def _solve_floor_aware_model(
    *,
    site_width_units: int,
    site_length_units: int,
    rooms: Sequence[Room],
    dimensions: Sequence[tuple[int, int]],
    room_indices: dict[str, int],
    time_limit_seconds: float,
    relationships: Sequence[RoomRelationship],
    number_of_floors: int,
    parking_type: str,
    parking_dimensions: tuple[int, int] | None,
    road_access: str,
    staircase_dimensions: tuple[int, int] | None,
    buildable_bounds_units: tuple[int, int, int, int],
) -> LayoutResult:
    model = cp_model.CpModel()
    x_positions: list[cp_model.IntVar] = []
    y_positions: list[cp_model.IntVar] = []
    x_intervals = []
    y_intervals = []
    floor_room_indices = {floor: [] for floor in range(1, number_of_floors + 1)}
    buildable_x_min, buildable_y_min, buildable_x_max, buildable_y_max = (
        buildable_bounds_units
    )

    for index, room in enumerate(rooms):
        width_units, length_units = dimensions[index]
        x = model.new_int_var(
            buildable_x_min, buildable_x_max - width_units, f"room_{index}_x"
        )
        y = model.new_int_var(
            buildable_y_min, buildable_y_max - length_units, f"room_{index}_y"
        )
        model.add(x + width_units <= buildable_x_max)
        model.add(y + length_units <= buildable_y_max)
        x_positions.append(x)
        y_positions.append(y)
        x_intervals.append(
            model.new_fixed_size_interval_var(x, width_units, f"room_{index}_x_interval")
        )
        y_intervals.append(
            model.new_fixed_size_interval_var(y, length_units, f"room_{index}_y_interval")
        )
        floor_room_indices[room.floor].append(index)

    staircase_positions: list[tuple[int, int, cp_model.IntVar, cp_model.IntVar, object, object]] = []
    floor_staircase_indices = {floor: [] for floor in range(1, number_of_floors + 1)}
    if staircase_dimensions is not None:
        stair_width, stair_length = staircase_dimensions
        x = model.new_int_var(
            buildable_x_min, buildable_x_max - stair_width, "staircase_x"
        )
        y = model.new_int_var(
            buildable_y_min, buildable_y_max - stair_length, "staircase_y"
        )
        model.add(x + stair_width <= buildable_x_max)
        model.add(y + stair_length <= buildable_y_max)
        x_interval = model.new_fixed_size_interval_var(
            x, stair_width, "staircase_x_interval"
        )
        y_interval = model.new_fixed_size_interval_var(
            y, stair_length, "staircase_y_interval"
        )
        staircase_positions.append(
            (1, number_of_floors, x, y, x_interval, y_interval)
        )
        for floor in range(1, number_of_floors + 1):
            floor_staircase_indices[floor].append(0)

    for floor in range(1, number_of_floors + 1):
        floor_x_intervals = [
            x_intervals[index] for index in floor_room_indices[floor]
        ]
        floor_y_intervals = [
            y_intervals[index] for index in floor_room_indices[floor]
        ]
        for stair_index in floor_staircase_indices[floor]:
            floor_x_intervals.append(staircase_positions[stair_index][4])
            floor_y_intervals.append(staircase_positions[stair_index][5])
        if len(floor_x_intervals) > 1:
            model.add_no_overlap_2d(floor_x_intervals, floor_y_intervals)

    parking_vars: tuple[cp_model.IntVar, cp_model.IntVar, object, object] | None = None
    parking_access_distance: cp_model.IntVar | None = None
    if parking_dimensions is not None:
        parking_width_units, parking_length_units = parking_dimensions
        parking_x = model.new_int_var(0, site_width_units, "parking_x")
        parking_y = model.new_int_var(0, site_length_units, "parking_y")
        model.add(parking_x + parking_width_units <= site_width_units)
        model.add(parking_y + parking_length_units <= site_length_units)
        parking_x_interval = model.new_fixed_size_interval_var(
            parking_x, parking_width_units, "parking_x_interval"
        )
        parking_y_interval = model.new_fixed_size_interval_var(
            parking_y, parking_length_units, "parking_y_interval"
        )
        parking_vars = (
            parking_x,
            parking_y,
            parking_x_interval,
            parking_y_interval,
        )

        for index in range(len(rooms)):
            model.add_no_overlap_2d(
                [parking_x_interval, x_intervals[index]],
                [parking_y_interval, y_intervals[index]],
            )
        for _, _, _, _, stair_x_interval, stair_y_interval in staircase_positions:
            model.add_no_overlap_2d(
                [parking_x_interval, stair_x_interval],
                [parking_y_interval, stair_y_interval],
            )

        if road_access in {"South", "North"}:
            parking_access_distance = model.new_int_var(
                0, site_length_units, "parking_access_distance"
            )
        else:
            parking_access_distance = model.new_int_var(
                0, site_width_units, "parking_access_distance"
            )
        if road_access == "South":
            model.add(parking_access_distance == parking_y)
        elif road_access == "North":
            model.add(
                parking_access_distance
                == site_length_units - parking_y - parking_length_units
            )
        elif road_access == "West":
            model.add(parking_access_distance == parking_x)
        else:
            model.add(
                parking_access_distance
                == site_width_units - parking_x - parking_width_units
            )

    near_distances: list[cp_model.IntVar] = []
    preferred_penalties: list[cp_model.IntVar] = []
    stacked_distances_half_units: list[cp_model.IntVar] = []
    for relationship_index, relationship in enumerate(relationships):
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

        if relationship.kind == "STACKED":
            center_dx = model.new_int_var(
                0, 2 * site_width_units, f"rel_{relationship_index}_center_dx"
            )
            center_dy = model.new_int_var(
                0, 2 * site_length_units, f"rel_{relationship_index}_center_dy"
            )
            model.add_abs_equality(
                center_dx,
                2 * x_positions[first_index]
                + first_width
                - 2 * x_positions[second_index]
                - second_width,
            )
            model.add_abs_equality(
                center_dy,
                2 * y_positions[first_index]
                + first_length
                - 2 * y_positions[second_index]
                - second_length,
            )
            stacked_distance = model.new_int_var(
                0,
                2 * (site_width_units + site_length_units),
                f"rel_{relationship_index}_stacked_distance",
            )
            model.add(stacked_distance == center_dx + center_dy)
            stacked_distances_half_units.append(stacked_distance)
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

    bbox_area_vars: list[cp_model.IntVar] = []
    bbox_dimension_terms: list[cp_model.IntVar] = []
    for floor in range(1, number_of_floors + 1):
        indices = floor_room_indices[floor]
        if not indices:
            continue
        left = model.new_int_var(0, site_width_units, f"floor_{floor}_left")
        right = model.new_int_var(0, site_width_units, f"floor_{floor}_right")
        bottom = model.new_int_var(0, site_length_units, f"floor_{floor}_bottom")
        top = model.new_int_var(0, site_length_units, f"floor_{floor}_top")
        width = model.new_int_var(0, site_width_units, f"floor_{floor}_bbox_width")
        length = model.new_int_var(0, site_length_units, f"floor_{floor}_bbox_length")
        model.add_min_equality(left, [x_positions[index] for index in indices])
        model.add_max_equality(
            right,
            [x_positions[index] + dimensions[index][0] for index in indices],
        )
        model.add_min_equality(bottom, [y_positions[index] for index in indices])
        model.add_max_equality(
            top,
            [y_positions[index] + dimensions[index][1] for index in indices],
        )
        model.add(width == right - left)
        model.add(length == top - bottom)
        area = model.new_int_var(
            0, site_width_units * site_length_units, f"floor_{floor}_bbox_area"
        )
        model.add_multiplication_equality(area, [width, length])
        bbox_area_vars.append(area)
        bbox_dimension_terms.extend([width, length])

    total_bbox_area = model.new_int_var(
        0,
        site_width_units * site_length_units * max(1, number_of_floors),
        "total_occupied_bbox_area",
    )
    model.add(total_bbox_area == sum(bbox_area_vars) if bbox_area_vars else total_bbox_area == 0)

    objective_stages = [("occupied bounding-box area", total_bbox_area)]
    if bbox_dimension_terms:
        objective_stages.append(
            ("occupied bounding-box dimensions", sum(bbox_dimension_terms))
        )
    if near_distances:
        objective_stages.append(("NEAR distance", sum(near_distances)))
    if preferred_penalties:
        objective_stages.append(("PREFERRED penalty", sum(preferred_penalties)))
    if stacked_distances_half_units:
        objective_stages.append(
            ("STACKED center distance", sum(stacked_distances_half_units))
        )
    if parking_access_distance is not None:
        objective_stages.append(("parking road-side distance", parking_access_distance))
    position_terms = [*x_positions, *y_positions]
    position_terms.extend(stair[2] for stair in staircase_positions)
    position_terms.extend(stair[3] for stair in staircase_positions)
    if parking_vars is not None:
        position_terms.extend(parking_vars[:2])
    if position_terms:
        objective_stages.append(
            ("lower-left placement", sum(position_terms))
        )

    start_time = time.monotonic()
    last_solver: cp_model.CpSolver | None = None
    all_stages_optimal = True
    for stage_index, (_, objective) in enumerate(objective_stages):
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
                return LayoutResult(
                    status=solver.status_name(status_code),
                    placements=[],
                    message="CP-SAT did not find a feasible arrangement.",
                    number_of_floors=number_of_floors,
                    parking_type=parking_type,
                    road_access=road_access,
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
            number_of_floors=number_of_floors,
            parking_type=parking_type,
            road_access=road_access,
        )

    placements = [
        Placement(
            name=room.name,
            x=last_solver.value(x_positions[index]) / GRID_UNITS_PER_METER,
            y=last_solver.value(y_positions[index]) / GRID_UNITS_PER_METER,
            width=dimensions[index][0] / GRID_UNITS_PER_METER,
            length=dimensions[index][1] / GRID_UNITS_PER_METER,
            floor=room.floor,
        )
        for index, room in enumerate(rooms)
    ]
    staircases = []
    if staircase_dimensions is not None:
        stair_width, stair_length = staircase_dimensions
        for index, (lower_floor, upper_floor, x, y, _, _) in enumerate(
            staircase_positions
        ):
            staircases.append(
                Placement(
                    name=f"Staircase F{lower_floor}-F{upper_floor}",
                    x=last_solver.value(x) / GRID_UNITS_PER_METER,
                    y=last_solver.value(y) / GRID_UNITS_PER_METER,
                    width=stair_width / GRID_UNITS_PER_METER,
                    length=stair_length / GRID_UNITS_PER_METER,
                    floor=lower_floor,
                    floor_end=upper_floor,
                )
            )

    parking = None
    if parking_vars is not None and parking_dimensions is not None:
        parking_width_units, parking_length_units = parking_dimensions
        parking = Placement(
            name=f"Parking ({parking_type})",
            x=last_solver.value(parking_vars[0]) / GRID_UNITS_PER_METER,
            y=last_solver.value(parking_vars[1]) / GRID_UNITS_PER_METER,
            width=parking_width_units / GRID_UNITS_PER_METER,
            length=parking_length_units / GRID_UNITS_PER_METER,
            floor=0,
            floor_end=0,
        )

    status = "OPTIMAL" if all_stages_optimal else "FEASIBLE"
    message = (
        "All objective stages were optimized."
        if status == "OPTIMAL"
        else "A feasible layout was found; some objective stages were not proven optimal before the time limit."
    )
    return LayoutResult(
        status=status,
        placements=placements,
        message=message,
        parking=parking,
        staircases=staircases,
        number_of_floors=number_of_floors,
        parking_type=parking_type,
        road_access=road_access,
    )