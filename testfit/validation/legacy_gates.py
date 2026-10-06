"""Gate and door points exactly as the current app draws them.

The current solver has no gate variables: ``visualization.create_floor_plan``
projects the parking center and the entrance-room center onto the road edge
after solving. Step 1 measures that behavior as the baseline. From Step 2 on,
gates come from the layout result and this module is only used for comparison.
"""

from __future__ import annotations

from testfit.validation.snapshot import Point, RectSpec

SIDES = {"North", "South", "East", "West"}


def project_to_side(
    x: float, y: float, side: str, site_width: float, site_length: float
) -> Point:
    side = side.title()
    if side == "South":
        return max(0.0, min(site_width, x)), 0.0
    if side == "North":
        return max(0.0, min(site_width, x)), site_length
    if side == "West":
        return 0.0, max(0.0, min(site_length, y))
    if side == "East":
        return site_width, max(0.0, min(site_length, y))
    raise ValueError("Side must be North, South, East, or West.")


def door_point(room: RectSpec, side: str) -> Point:
    """Midpoint of the room edge facing ``side`` (where the app draws the door)."""
    side = side.title()
    if side == "North":
        return room.x + room.width / 2, room.y + room.length
    if side == "South":
        return room.x + room.width / 2, room.y
    if side == "East":
        return room.x + room.width, room.y + room.length / 2
    if side == "West":
        return room.x, room.y + room.length / 2
    raise ValueError("Side must be North, South, East, or West.")


def legacy_gate_points(
    *,
    site_width: float,
    site_length: float,
    road_access: str,
    entrance_side: str,
    parking: RectSpec | None,
    entrance_room: RectSpec | None,
) -> dict[str, Point | None]:
    if parking is not None:
        vehicle = project_to_side(
            parking.x + parking.width / 2,
            parking.y + parking.length / 2,
            road_access,
            site_width,
            site_length,
        )
    else:
        vehicle = project_to_side(
            site_width / 2, site_length / 2, road_access, site_width, site_length
        )
    if entrance_room is not None:
        pedestrian = project_to_side(
            entrance_room.x + entrance_room.width / 2,
            entrance_room.y + entrance_room.length / 2,
            entrance_side,
            site_width,
            site_length,
        )
        door: Point | None = door_point(entrance_room, entrance_side)
    else:
        pedestrian = project_to_side(
            site_width / 2, site_length / 2, entrance_side, site_width, site_length
        )
        door = None
    return {"vehicle_gate": vehicle, "pedestrian_gate": pedestrian, "entrance_door": door}
