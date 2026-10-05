"""Unit conversion and transparent preliminary room-program recommendations."""

from __future__ import annotations

import math
from collections.abc import Sequence

from testfit.optimizer import Placement, Room, RoomRelationship

FEET_PER_METER = 1 / 0.3048
SQUARE_FEET_PER_SQUARE_METER = FEET_PER_METER**2
STAIRCASE_DEFAULT_FEET = (6.5, 13.0)
PARKING_DEFAULT_FEET = {
    "1 car": (9.0, 18.0),
    "2 cars": (18.0, 18.0),
}
BUILDING_TYPES = (
    "Single-Family House",
    "Duplex",
    "Rental / Multi-Unit Building",
    "Apartment / Multi-Unit Residential",
    "Custom",
)


def feet_to_meters(value: float) -> float:
    """Convert a finite distance in feet to meters."""
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Distance in feet must be finite.")
    return value * 0.3048


def meters_to_feet(value: float) -> float:
    """Convert a finite distance in meters to feet."""
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Distance in meters must be finite.")
    return value / 0.3048


def feet_area_to_square_meters(value: float) -> float:
    return float(value) / SQUARE_FEET_PER_SQUARE_METER


def square_meters_to_feet(value: float) -> float:
    return float(value) * SQUARE_FEET_PER_SQUARE_METER


def floor_label(floor: int) -> str:
    return {
        1: "Ground Floor",
        2: "First Floor",
        3: "Second Floor",
        4: "Third Floor",
        5: "Fourth Floor",
    }.get(floor, f"Floor {floor}")


def select_entrance_room(
    placements: Sequence[Placement], side: str
) -> Placement | None:
    """Choose the most appropriate ground-floor room for the main entrance.

    Prefer foyer/entry/common rooms, but rank them by actual distance to the
    requested exterior side. This avoids selecting a visually convenient room
    that is deep inside the building.
    """
    candidates = [
        room
        for room in placements
        if room.floor == 1 and "bathroom" not in room.name.casefold()
    ]
    if not candidates:
        return None
    side = side.title()
    keyword_priority = (
        "entry foyer",
        "foyer",
        "entrance",
        "living",
        "dining",
        "kitchen",
    )

    def edge_distance(room: Placement) -> float:
        if side == "North":
            return max(0.0, max(room.y + room.length, 0.0))
        if side == "South":
            return max(0.0, room.y)
        if side == "East":
            return max(0.0, room.x)
        if side == "West":
            return max(0.0, room.x)
        raise ValueError("Entrance side must be North, South, East, or West.")

    def frontage_gap(room: Placement) -> float:
        if side == "North":
            return max(0.0, -room.y - room.length)
        if side == "South":
            return max(0.0, room.y)
        if side == "East":
            return max(0.0, -room.x - room.width)
        return max(0.0, room.x)

    def keyword_rank(room: Placement) -> int:
        name = room.name.casefold()
        for rank, keyword in enumerate(keyword_priority):
            if keyword in name:
                return rank
        return len(keyword_priority)

    # The solver now places the primary anchor on the road-facing buildable
    # edge. This ranking remains defensive for custom programs and older saved
    # layouts.
    return min(
        candidates,
        key=lambda room: (frontage_gap(room), keyword_rank(room), edge_distance(room)),
    )


def setback_bounds_feet(
    site_width: float,
    site_length: float,
    road_access: str,
    front: float,
    rear: float,
    left: float,
    right: float,
) -> tuple[float, float, float, float]:
    """Return the buildable rectangle as x-min, y-min, x-max, y-max in feet.

    Left and right setbacks are interpreted while facing the site from the road.
    """
    front_side = road_access.title()
    if front_side not in {"North", "South", "East", "West"}:
        raise ValueError("Road access must be North, South, East, or West.")
    side_setbacks = {
        "North": {"front": "North", "rear": "South", "left": "East", "right": "West"},
        "South": {"front": "South", "rear": "North", "left": "West", "right": "East"},
        "East": {"front": "East", "rear": "West", "left": "South", "right": "North"},
        "West": {"front": "West", "rear": "East", "left": "North", "right": "South"},
    }[front_side]
    values = {"front": front, "rear": rear, "left": left, "right": right}
    side_values = {side: float(values[name]) for name, side in side_setbacks.items()}
    if any(not math.isfinite(value) or value < 0 for value in side_values.values()):
        raise ValueError("Setbacks must be finite values greater than or equal to zero.")
    x_min = side_values["West"]
    y_min = side_values["South"]
    x_max = float(site_width) - side_values["East"]
    y_max = float(site_length) - side_values["North"]
    if x_min >= x_max or y_min >= y_max:
        raise ValueError("Setbacks must leave a positive buildable area inside the site.")
    return x_min, y_min, x_max, y_max


def recommend_room_program(
    *,
    buildable_bounds_ft: tuple[float, float, float, float],
    number_of_floors: int,
    building_type: str,
    units_per_floor: int = 1,
    parking_area_ft2: float = 0.0,
    staircase_size_ft: tuple[float, float] = STAIRCASE_DEFAULT_FEET,
) -> tuple[list[Room], list[RoomRelationship], float]:
    """Build an explainable, area-based residential program in solver meters.

    The returned area is the approximate gross area per floor in square feet.
    Recommendations are planning guidance, not architectural standards.
    """
    x_min, y_min, x_max, y_max = buildable_bounds_ft
    floor_area_ft2 = (x_max - x_min) * (y_max - y_min)
    staircase_area_ft2 = (
        staircase_size_ft[0] * staircase_size_ft[1] * number_of_floors
        if number_of_floors > 1
        else 0.0
    )
    usable_total_ft2 = max(
        0.0,
        (
            floor_area_ft2 * number_of_floors
            - max(0.0, parking_area_ft2)
            - staircase_area_ft2
        )
        * 0.82,
    )
    rooms_ft: list[tuple[str, int, float, float]] = []
    relationships: list[RoomRelationship] = []

    if building_type in {
        "Rental / Multi-Unit Building",
        "Apartment / Multi-Unit Residential",
    }:
        for floor in range(1, number_of_floors + 1):
            for unit in range(1, units_per_floor + 1):
                prefix = f"Floor {floor} · Unit {unit}"
                living = f"{prefix} Living"
                bedroom = f"{prefix} Bedroom"
                kitchen = f"{prefix} Kitchen"
                bathroom = f"{prefix} Bathroom"
                rooms_ft.extend(
                    [
                        (living, floor, 10, 12),
                        (bedroom, floor, 10, 11),
                        (kitchen, floor, 7, 8),
                        (bathroom, floor, 5, 8),
                    ]
                )
                relationships.extend(
                    [
                        RoomRelationship(bedroom, bathroom, "ATTACHED"),
                        RoomRelationship(living, kitchen, "NEAR"),
                    ]
                )
        return (
            [
                Room(name, feet_to_meters(width), feet_to_meters(length), floor)
                for name, floor, width, length in rooms_ft
            ],
            relationships,
            floor_area_ft2,
        )

    bedrooms = max(1, min(5, int(usable_total_ft2 // 450)))
    bathrooms = min(bedrooms, max(1, math.ceil(bedrooms / 2)))
    rooms_ft.extend(
        [
            ("Entry Foyer", 1, 6, 7),
            ("Living Room", 1, 14, 16),
            ("Kitchen", 1, 10, 11),
            ("Dining", 1, 9, 10),
        ]
    )
    if usable_total_ft2 >= 850:
        rooms_ft.append(("Utility", 1, 6, 7))

    bedroom_floors: list[int] = []
    for index in range(bedrooms):
        if number_of_floors == 1:
            floor = 1
        elif building_type == "Duplex" and index == 0:
            floor = 1
        else:
            floor = 2 + (index - (1 if building_type == "Duplex" else 0)) % (
                number_of_floors - 1
            )
        bedroom_floors.append(floor)
        size = (12, 12) if index == 0 else (11, 12)
        rooms_ft.append((f"Bedroom {index + 1}", floor, *size))

    for index in range(bathrooms):
        floor = bedroom_floors[index]
        bathroom_name = f"Bathroom {index + 1}"
        rooms_ft.append((bathroom_name, floor, 5, 8))
        relationships.append(
            RoomRelationship(f"Bedroom {index + 1}", bathroom_name, "ATTACHED")
        )
    relationships.extend(
        [
            RoomRelationship("Kitchen", "Dining", "ADJACENT"),
            RoomRelationship("Living Room", "Dining", "NEAR"),
            RoomRelationship("Kitchen", "Dining", "PREFERRED"),
        ]
    )
    if number_of_floors > 1 and bedrooms >= 3:
        rooms_ft.append(("Family Lounge", number_of_floors, 11, 12))

    rooms = [
        Room(name, feet_to_meters(width), feet_to_meters(length), floor)
        for name, floor, width, length in rooms_ft
    ]
    return rooms, relationships, floor_area_ft2


def planning_suggestions(
    *,
    floor_area_ft2: float,
    number_of_floors: int,
    parking_type: str,
    bedroom_count: int,
) -> list[str]:
    suggestions = []
    if floor_area_ft2 < 700 and bedroom_count >= 3:
        suggestions.append(
            "With this buildable area, fewer bedrooms may allow a more comfortable layout."
        )
    if number_of_floors == 1 and floor_area_ft2 > 900:
        suggestions.append("An additional floor could allow more bedrooms or larger rooms.")
    if parking_type == "2 cars":
        suggestions.append(
            "Two-car parking uses more site area and may reduce the available open area."
        )
    if number_of_floors > 1:
        suggestions.append(
            "Moving some bedrooms to upper floors can leave more room for ground-floor circulation."
        )
    return suggestions
