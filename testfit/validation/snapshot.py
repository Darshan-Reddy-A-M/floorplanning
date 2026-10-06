"""Solver-independent description of a generated layout.

A ``LayoutSnapshot`` holds only output coordinates (meters) plus the inputs
needed to judge them. The validation package never imports OR-Tools, so a saved
snapshot can be re-checked on any machine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence


@dataclass
class RectSpec:
    """Axis-aligned rectangle in meters. ``floor_end`` is inclusive; None = single floor."""

    name: str
    x: float
    y: float
    width: float
    length: float
    floor: int = 1
    floor_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RectSpec":
        return cls(**data)


def as_rect(obj: Any) -> RectSpec:
    """Build a RectSpec from any object exposing Placement-like attributes."""
    return RectSpec(
        name=str(obj.name),
        x=float(obj.x),
        y=float(obj.y),
        width=float(obj.width),
        length=float(obj.length),
        floor=int(getattr(obj, "floor", 1)),
        floor_end=(
            None
            if getattr(obj, "floor_end", None) is None
            else int(obj.floor_end)
        ),
    )


Point = tuple[float, float]


@dataclass
class LayoutSnapshot:
    site_width: float
    site_length: float
    number_of_floors: int
    rooms: list[RectSpec] = field(default_factory=list)
    staircases: list[RectSpec] = field(default_factory=list)
    parking: RectSpec | None = None
    buildable_bounds: tuple[float, float, float, float] | None = None
    relationships: list[tuple[str, str, str]] = field(default_factory=list)
    road_access: str = "South"
    entrance_side: str | None = None
    entrance_room: str | None = None
    vehicle_gate: Point | None = None
    pedestrian_gate: Point | None = None
    entrance_door: Point | None = None
    # Where the gate/door points came from: "none", "legacy_projection"
    # (reproduces how app.py/visualization.py draw them today) or "layout".
    gate_source: str = "none"
    # Optional inputs used to verify that the solver kept requested sizes.
    expected_rooms: dict[str, tuple[float, float, int]] | None = None
    expected_parking: tuple[float, float] | None = None
    expected_staircase: tuple[float, float] | None = None
    status: str = "UNKNOWN"
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.buildable_bounds or (0.0, 0.0, self.site_width, self.site_length)

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_width": self.site_width,
            "site_length": self.site_length,
            "number_of_floors": self.number_of_floors,
            "rooms": [r.to_dict() for r in self.rooms],
            "staircases": [r.to_dict() for r in self.staircases],
            "parking": None if self.parking is None else self.parking.to_dict(),
            "buildable_bounds": (
                None if self.buildable_bounds is None else list(self.buildable_bounds)
            ),
            "relationships": [list(r) for r in self.relationships],
            "road_access": self.road_access,
            "entrance_side": self.entrance_side,
            "entrance_room": self.entrance_room,
            "vehicle_gate": self.vehicle_gate and list(self.vehicle_gate),
            "pedestrian_gate": self.pedestrian_gate and list(self.pedestrian_gate),
            "entrance_door": self.entrance_door and list(self.entrance_door),
            "gate_source": self.gate_source,
            "expected_rooms": (
                None
                if self.expected_rooms is None
                else {k: list(v) for k, v in self.expected_rooms.items()}
            ),
            "expected_parking": self.expected_parking and list(self.expected_parking),
            "expected_staircase": self.expected_staircase
            and list(self.expected_staircase),
            "status": self.status,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LayoutSnapshot":
        def pt(value):
            return None if value is None else (float(value[0]), float(value[1]))

        expected = data.get("expected_rooms")
        return cls(
            site_width=data["site_width"],
            site_length=data["site_length"],
            number_of_floors=data["number_of_floors"],
            rooms=[RectSpec.from_dict(r) for r in data.get("rooms", [])],
            staircases=[RectSpec.from_dict(r) for r in data.get("staircases", [])],
            parking=(
                None if data.get("parking") is None else RectSpec.from_dict(data["parking"])
            ),
            buildable_bounds=(
                None
                if data.get("buildable_bounds") is None
                else tuple(data["buildable_bounds"])
            ),
            relationships=[tuple(r) for r in data.get("relationships", [])],
            road_access=data.get("road_access", "South"),
            entrance_side=data.get("entrance_side"),
            entrance_room=data.get("entrance_room"),
            vehicle_gate=pt(data.get("vehicle_gate")),
            pedestrian_gate=pt(data.get("pedestrian_gate")),
            entrance_door=pt(data.get("entrance_door")),
            gate_source=data.get("gate_source", "none"),
            expected_rooms=(
                None
                if expected is None
                else {k: (v[0], v[1], int(v[2])) for k, v in expected.items()}
            ),
            expected_parking=(
                None
                if data.get("expected_parking") is None
                else tuple(data["expected_parking"])
            ),
            expected_staircase=(
                None
                if data.get("expected_staircase") is None
                else tuple(data["expected_staircase"])
            ),
            status=data.get("status", "UNKNOWN"),
            meta=data.get("meta", {}),
        )


def snapshot_from_layout(
    result: Any,
    *,
    site_width: float,
    site_length: float,
    relationships: Sequence[Any] = (),
    buildable_bounds: tuple[float, float, float, float] | None = None,
    entrance_side: str | None = None,
    entrance_room: str | None = None,
    expected_rooms: Sequence[Any] | None = None,
    expected_parking: tuple[float, float] | None = None,
    expected_staircase: tuple[float, float] | None = None,
    meta: dict[str, Any] | None = None,
) -> LayoutSnapshot:
    """Convert a ``LayoutResult``-like object (duck-typed) into a snapshot."""
    return LayoutSnapshot(
        site_width=float(site_width),
        site_length=float(site_length),
        number_of_floors=int(result.number_of_floors),
        rooms=[as_rect(p) for p in result.placements],
        staircases=[as_rect(p) for p in result.staircases],
        parking=None if result.parking is None else as_rect(result.parking),
        buildable_bounds=buildable_bounds,
        relationships=[(r.room_a, r.room_b, r.kind) for r in relationships],
        road_access=str(result.road_access),
        entrance_side=entrance_side,
        entrance_room=entrance_room,
        expected_rooms=(
            None
            if expected_rooms is None
            else {r.name: (float(r.width), float(r.length), int(r.floor)) for r in expected_rooms}
        ),
        expected_parking=expected_parking,
        expected_staircase=expected_staircase,
        status=str(result.status),
        meta=dict(meta or {}),
    )
