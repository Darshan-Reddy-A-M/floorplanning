"""Spatial-quality measurements computed from output coordinates.

All lengths are meters and areas square meters in the returned dictionaries.
The room-type keyword lists below are a *placeholder* classification used only
to measure the baseline; Step 3 replaces them with the hand-authored knowledge
layer.
"""

from __future__ import annotations

import math
from collections import deque

from testfit.validation.geometry import (
    CM,
    DOOR_MIN_CM,
    Box,
    floor_boxes,
    parking_box,
    rect_gap_cm,
    room_boxes,
    shared_edge_cm,
    stair_boxes,
    to_box,
    uncovered_area_cm2,
    union_area_cm2,
    void_analysis,
    cm,
)
from testfit.validation.snapshot import LayoutSnapshot

CIRCULATION_WORDS = ("foyer", "entry", "entrance", "hall", "corridor", "lobby",
                     "landing", "passage", "vestibule")
PRIVATE_WORDS = ("bedroom", "bathroom", "bath", "toilet", "master")
COMMON_WORDS = ("living", "family", "lounge", "dining")
SERVICE_WORDS = ("kitchen", "utility", "store", "laundry", "pantry")
HABITABLE_WORDS = ("bedroom", "living", "dining", "family", "lounge", "kitchen", "master")
SOFT_NEAR_M = 1.0
STACKED_M = 1.0
ASPECT_FLAG = 2.5


def classify_room(name: str) -> str:
    text = name.casefold()
    for label, words in (
        ("circulation", CIRCULATION_WORDS),
        ("private", PRIVATE_WORDS),
        ("common", COMMON_WORDS),
        ("service", SERVICE_WORDS),
    ):
        if any(w in text for w in words):
            return label
    return "other"


def _m(value_cm: float) -> float:
    return value_cm / CM


def _m2(value_cm2: float) -> float:
    return value_cm2 / (CM * CM)


def _point_to_box_m(point: tuple[float, float], box: Box) -> float:
    px, py = cm(point[0]), cm(point[1])
    dx = max(box.x0 - px, 0, px - box.x1)
    dy = max(box.y0 - py, 0, py - box.y1)
    return _m(math.hypot(dx, dy))


def _components(boxes: list[Box], min_edge_cm: int) -> list[list[str]]:
    """Connected groups of boxes whose shared edges are at least ``min_edge_cm``."""
    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            if shared_edge_cm(a, boxes[j]) >= min_edge_cm:
                parent[find(i)] = find(j)
    groups: dict[int, list[str]] = {}
    for i, b in enumerate(boxes):
        groups.setdefault(find(i), []).append(b.name)
    return list(groups.values())


def floor_metrics(snapshot: LayoutSnapshot, floor: int) -> dict:
    boxes = floor_boxes(snapshot, floor)
    rooms = [b for b in room_boxes(snapshot) if b.on_floor(floor)]
    if not boxes:
        return {"floor": floor, "n_rooms": 0}
    void = void_analysis(boxes)
    bx0, by0, bx1, by1 = (cm(v) for v in snapshot.bounds)
    buildable_area = (bx1 - bx0) * (by1 - by0)
    isolated = [
        b.name
        for i, b in enumerate(boxes)
        if not any(shared_edge_cm(b, o) > 0 for j, o in enumerate(boxes) if j != i)
    ]
    touching = _components(boxes, 1)
    connectable = _components(boxes, DOOR_MIN_CM)

    enclosed, exposure = [], {}
    for r in rooms:
        if not any(w in r.name.casefold() for w in HABITABLE_WORDS):
            continue
        perimeter = 2 * (r.width + r.length)
        shared = sum(shared_edge_cm(r, o) for o in boxes if o is not r and o.name != r.name)
        exposure[r.name] = _m(max(0, perimeter - shared))
        if perimeter - shared <= 0:
            enclosed.append(r.name)
    aspects = {
        r.name: max(r.width, r.length) / min(r.width, r.length) for r in rooms
    }
    return {
        "floor": floor,
        "n_rooms": len(rooms),
        "room_area_m2": _m2(sum(r.area for r in rooms)),
        "bbox_m": [_m(void["bbox_w"]), _m(void["bbox_l"])],
        "bbox_area_m2": _m2(void["bbox_area"]),
        "union_area_m2": _m2(void["union_area"]),
        "void_area_m2": _m2(void["void_area"]),
        "void_pct": (
            void["void_area"] / void["bbox_area"] * 100 if void["bbox_area"] else 0.0
        ),
        "void_components": void["void_components"],
        "largest_void_m2": _m2(void["largest_void_area"]),
        "largest_empty_rect_m2": _m2(void["largest_empty_rect_area"]),
        "largest_empty_rect_dims_m": [_m(v) for v in void["largest_empty_rect_dims"]],
        "buildable_coverage_pct": (
            void["union_area"] / buildable_area * 100 if buildable_area else 0.0
        ),
        "isolated_elements": isolated,
        "clusters_touching": len(touching),
        "clusters_connectable": len(connectable),
        "cluster_sizes_connectable": sorted((len(c) for c in connectable), reverse=True),
        "habitable_exposure_m": exposure,
        "fully_enclosed_habitable": enclosed,
        "max_aspect_ratio": max(aspects.values()) if aspects else 0.0,
        "rooms_aspect_over_2_5": sorted(n for n, a in aspects.items() if a > ASPECT_FLAG),
    }


def stair_metrics(snapshot: LayoutSnapshot) -> list[dict]:
    """Per stair and served floor: how well the shaft opens onto circulation."""
    result = []
    rooms = room_boxes(snapshot)
    for stair in stair_boxes(snapshot):
        for floor in range(stair.f0, stair.f1 + 1):
            edges = {"circulation": 0, "common": 0, "service": 0, "private": 0, "other": 0}
            for room in (r for r in rooms if r.on_floor(floor)):
                edge = shared_edge_cm(stair, room)
                kind = classify_room(room.name)
                edges[kind] = max(edges[kind], edge)
            if edges["circulation"] >= DOOR_MIN_CM:
                connection = "circulation"
            elif edges["common"] >= DOOR_MIN_CM:
                connection = "common_room"
            elif max(edges["service"], edges["private"], edges["other"]) >= DOOR_MIN_CM:
                connection = "private_or_service_only"
            else:
                connection = "none"
            result.append(
                {
                    "stair": stair.name,
                    "floor": floor,
                    "connection": connection,
                    "edge_m": {k: _m(v) for k, v in edges.items()},
                }
            )
    return result


def reachability(snapshot: LayoutSnapshot) -> dict:
    """Door-capable adjacency graph (shared edge >= 0.9 m); stairs link floors."""
    entrance = next(
        (
            b
            for b in room_boxes(snapshot)
            if b.name == snapshot.entrance_room and b.on_floor(1)
        ),
        None,
    )
    nodes: dict[tuple[str, int], Box] = {}
    for floor in range(1, snapshot.number_of_floors + 1):
        for b in floor_boxes(snapshot, floor):
            nodes[(b.name, floor)] = b
    if entrance is None:
        return {"entrance_found": False, "unreachable": sorted({n for n, _ in nodes}),
                "max_depth": None, "n_nodes": len(nodes)}
    adjacency: dict[tuple[str, int], set] = {k: set() for k in nodes}
    keys = list(nodes)
    for i, ka in enumerate(keys):
        for kb in keys[i + 1 :]:
            if ka[1] == kb[1] and shared_edge_cm(nodes[ka], nodes[kb]) >= DOOR_MIN_CM:
                adjacency[ka].add(kb)
                adjacency[kb].add(ka)
    stair_names = {b.name for b in stair_boxes(snapshot)}
    for (name, floor) in keys:
        if name in stair_names and (name, floor + 1) in nodes:
            adjacency[(name, floor)].add((name, floor + 1))
            adjacency[(name, floor + 1)].add((name, floor))
    start = (entrance.name, 1)
    depth = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nxt in adjacency[node]:
            if nxt not in depth:
                depth[nxt] = depth[node] + 1
                queue.append(nxt)
    unreachable = sorted(f"{n} (floor {f})" for (n, f) in keys if (n, f) not in depth)
    return {
        "entrance_found": True,
        "unreachable": unreachable,
        "max_depth": max(depth.values()),
        "n_nodes": len(nodes),
    }


def site_metrics(snapshot: LayoutSnapshot) -> dict:
    out: dict = {"gate_source": snapshot.gate_source}
    park = parking_box(snapshot)
    veh, ped, door = snapshot.vehicle_gate, snapshot.pedestrian_gate, snapshot.entrance_door
    out["vehicle_gate_to_parking_m"] = (
        _point_to_box_m(veh, park) if park is not None and veh is not None else None
    )
    out["vehicle_gate_to_parking_center_m"] = (
        _m(
            math.hypot(
                cm(veh[0]) - sum((park.x0, park.x1)) / 2,
                cm(veh[1]) - sum((park.y0, park.y1)) / 2,
            )
        )
        if park is not None and veh is not None
        else None
    )
    side = snapshot.road_access.title()
    if park is not None:
        gap = {
            "South": park.y0,
            "North": cm(snapshot.site_length) - park.y1,
            "West": park.x0,
            "East": cm(snapshot.site_width) - park.x1,
        }[side]
        out["parking_gap_to_road_edge_m"] = _m(gap)
        bx0, by0, bx1, by1 = (cm(v) for v in snapshot.bounds)
        inside = max(0, min(park.x1, bx1) - max(park.x0, bx0)) * max(
            0, min(park.y1, by1) - max(park.y0, by0)
        )
        out["parking_inside_buildable_m2"] = _m2(inside)
    else:
        out["parking_gap_to_road_edge_m"] = None
        out["parking_inside_buildable_m2"] = None
    out["pedestrian_gate_to_door_m"] = (
        _m(math.hypot(cm(ped[0]) - cm(door[0]), cm(ped[1]) - cm(door[1])))
        if ped is not None and door is not None
        else None
    )
    out["gate_separation_m"] = (
        _m(math.hypot(cm(veh[0]) - cm(ped[0]), cm(veh[1]) - cm(ped[1])))
        if veh is not None and ped is not None
        else None
    )
    out["entrance_door_to_parking_m"] = (
        _point_to_box_m(door, park) if park is not None and door is not None else None
    )
    entrance_side = (snapshot.entrance_side or snapshot.road_access).title()
    room = next((b for b in room_boxes(snapshot) if b.name == snapshot.entrance_room), None)
    if room is not None:
        bx0, by0, bx1, by1 = (cm(v) for v in snapshot.bounds)
        gap = {
            "South": room.y0 - by0,
            "North": by1 - room.y1,
            "West": room.x0 - bx0,
            "East": bx1 - room.x1,
        }[entrance_side]
        out["entrance_room_gap_to_buildable_edge_m"] = _m(gap)
    else:
        out["entrance_room_gap_to_buildable_edge_m"] = None
    return out


def vertical_metrics(snapshot: LayoutSnapshot) -> dict:
    ground = floor_boxes(snapshot, 1)
    overhang = {}
    for floor in range(2, snapshot.number_of_floors + 1):
        upper = floor_boxes(snapshot, floor)
        overhang[floor] = _m2(uncovered_area_cm2(upper, ground)) if upper else 0.0
    return {"upper_floor_overhang_m2": overhang}


def relationship_metrics(snapshot: LayoutSnapshot) -> dict:
    by_name = {r.name: to_box(r) for r in snapshot.rooms}
    out = {"NEAR": [0, 0], "PREFERRED": [0, 0], "STACKED": [0, 0]}
    for a_name, b_name, raw in snapshot.relationships:
        kind = str(raw).upper()
        if kind not in out:
            continue
        a, b = by_name.get(a_name), by_name.get(b_name)
        out[kind][1] += 1
        if a is None or b is None:
            continue
        if kind == "STACKED":
            ax, ay = a.center2()
            bx, by = b.center2()
            ok = abs(a.f0 - b.f0) == 1 and (abs(ax - bx) + abs(ay - by)) / 2 <= STACKED_M * CM
        else:
            ok = a.f0 == b.f0 and rect_gap_cm(a, b) <= SOFT_NEAR_M * CM
        out[kind][0] += int(ok)
    return {k: {"satisfied": v[0], "total": v[1]} for k, v in out.items()}


def compute_quality(snapshot: LayoutSnapshot) -> dict:
    floors = [floor_metrics(snapshot, f) for f in range(1, snapshot.number_of_floors + 1)]
    return {
        "floors": floors,
        "stairs": stair_metrics(snapshot),
        "reachability": reachability(snapshot),
        "site": site_metrics(snapshot),
        "vertical": vertical_metrics(snapshot),
        "relationships": relationship_metrics(snapshot),
    }
