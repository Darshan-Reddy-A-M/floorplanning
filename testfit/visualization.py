"""Matplotlib floor-plan rendering."""

from __future__ import annotations

from collections.abc import Sequence
import textwrap

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

from testfit.planning import floor_label
from testfit.optimizer import Placement


def create_floor_plan(
    site_width: float,
    site_length: float,
    placements: Sequence[Placement],
    *,
    floor_number: int = 1,
    parking: Placement | None = None,
    staircases: Sequence[Placement] = (),
    buildable_bounds: tuple[float, float, float, float] | None = None,
    road_access: str = "South",
    entrance_side: str | None = None,
    entrance_room_name: str | None = None,
    relationships=(),
    unit_label: str = "m",
):
    """Create a labeled plan for one floor, including site-level elements."""
    figure, axis = plt.subplots(figsize=(10, 7))
    axis.add_patch(
        Rectangle(
            (0, 0),
            site_width,
            site_length,
            facecolor="#f8fafc",
            edgecolor="#26374a",
            linewidth=2.2,
            zorder=0,
        )
    )
    x_min, y_min, x_max, y_max = buildable_bounds or (
        0.0,
        0.0,
        site_width,
        site_length,
    )
    axis.add_patch(
        Rectangle(
            (x_min, y_min),
            x_max - x_min,
            y_max - y_min,
            facecolor="#dcfce7",
            edgecolor="#15803d",
            linewidth=1.4,
            hatch="..",
            alpha=0.23,
            zorder=0.5,
        )
    )

    colors = plt.get_cmap("tab20")
    for stair in staircases:
        stair_last_floor = stair.floor_end or stair.floor
        if stair.floor <= floor_number <= stair_last_floor:
            axis.add_patch(
                Rectangle(
                    (stair.x, stair.y),
                    stair.width,
                    stair.length,
                    facecolor="#dbeafe",
                    edgecolor="#1d4ed8",
                    linewidth=1.8,
                    hatch="///",
                    zorder=1,
                )
            )
            axis.text(
                stair.x + stair.width / 2,
                stair.y + stair.length / 2,
                f"{stair.name}\n{stair.width:.1f} × {stair.length:.1f} {unit_label}",
                ha="center",
                va="center",
                color="#1e3a8a",
                fontsize=8,
                fontweight="bold",
                zorder=3,
            )

    if parking is not None and floor_number == 1:
        axis.add_patch(
            Rectangle(
                (parking.x, parking.y),
                parking.width,
                parking.length,
                facecolor="#fef3c7",
                edgecolor="#92400e",
                linewidth=1.8,
                hatch="xx",
                zorder=1,
            )
        )
        axis.text(
            parking.x + parking.width / 2,
            parking.y + parking.length / 2,
            f"{parking.name}\n{parking.width:.1f} × {parking.length:.1f} {unit_label}",
            ha="center",
            va="center",
            color="#78350f",
            fontsize=8,
            fontweight="bold",
            zorder=3,
        )

    for index, room in enumerate(placements):
        color = colors(index % 20)
        axis.add_patch(
            Rectangle(
                (room.x, room.y),
                room.width,
                room.length,
                facecolor=color,
                edgecolor="#ffffff",
                linewidth=2,
                alpha=0.9,
                zorder=2,
            )
        )
        wrapped_name = textwrap.fill(
            room.name,
            width=max(6, int(room.width * 4)),
            break_long_words=True,
            break_on_hyphens=False,
        )
        label = f"{wrapped_name}\n{room.width:.1f} × {room.length:.1f} {unit_label}"
        axis.text(
            room.x + room.width / 2,
            room.y + room.length / 2,
            label,
            ha="center",
            va="center",
            color="#1f2937",
            fontsize=8 if room.width <= 2 else 9,
            fontweight="normal",
            wrap=True,
            zorder=3,
        )

    axis.set_xlim(-0.5, site_width + 0.5)
    axis.set_ylim(-0.5, site_length + 0.5)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel(f"Site width ({unit_label})")
    axis.set_ylabel(f"Site length ({unit_label})")
    axis.set_title(
        f"{floor_label(floor_number).upper()} — PLAN",
        loc="left",
        fontsize=14,
        fontweight="bold",
        pad=14,
    )
    road_access = road_access.title()
    entrance_side = (entrance_side or road_access).title()

    def project_to_road(x: float, y: float, side: str) -> tuple[float, float]:
        """Project a point to the selected road boundary."""
        if side == "South":
            return max(0.0, min(site_width, x)), 0.0
        if side == "North":
            return max(0.0, min(site_width, x)), site_length
        if side == "West":
            return 0.0, max(0.0, min(site_length, y))
        if side == "East":
            return site_width, max(0.0, min(site_length, y))
        raise ValueError("Road access must be North, South, East, or West.")

    entrance_room = next(
        (room for room in placements if room.name == (entrance_room_name or "") and room.floor == floor_number),
        None,
    )
    if parking is not None:
        gate_x, gate_y = project_to_road(
            parking.x + parking.width / 2, parking.y + parking.length / 2, road_access
        )
    else:
        gate_x, gate_y = project_to_road(site_width / 2, site_length / 2, road_access)

    if entrance_room is not None:
        pedestrian_gate_x, pedestrian_gate_y = project_to_road(
            entrance_room.x + entrance_room.width / 2,
            entrance_room.y + entrance_room.length / 2,
            entrance_side,
        )
    else:
        pedestrian_gate_x, pedestrian_gate_y = project_to_road(
            site_width / 2, site_length / 2, entrance_side
        )

    if floor_number == 1:
        axis.scatter([gate_x], [gate_y], marker="s", s=65, color="#b45309", zorder=6)
        axis.scatter(
            [pedestrian_gate_x],
            [pedestrian_gate_y],
            marker="^",
            s=70,
            color="#1d4ed8",
            zorder=6,
        )
        if road_access in {"North", "South"}:
            axis.annotate(
                "Vehicle gate",
                (gate_x, gate_y),
                xytext=(8, 10 if road_access == "South" else -18),
                textcoords="offset points",
                fontsize=8,
                color="#92400e",
            )
            axis.annotate(
                "Pedestrian gate",
                (pedestrian_gate_x, pedestrian_gate_y),
                xytext=(-70, 10 if road_access == "South" else -18),
                textcoords="offset points",
                fontsize=8,
                color="#1d4ed8",
            )
        else:
            axis.annotate(
                "Vehicle gate",
                (gate_x, gate_y),
                xytext=(8 if road_access == "West" else -75, 8),
                textcoords="offset points",
                fontsize=8,
                color="#92400e",
            )
            axis.annotate(
                "Pedestrian gate",
                (pedestrian_gate_x, pedestrian_gate_y),
                xytext=(8 if road_access == "West" else -75, -14),
                textcoords="offset points",
                fontsize=8,
                color="#1d4ed8",
            )

    actual_rooms = {room.name: room for room in placements}
    floor_room_list = list(actual_rooms.values())
    for index, first in enumerate(floor_room_list):
        for second in floor_room_list[index + 1 :]:
            if abs(first.x + first.width - second.x) < 1e-8 or abs(
                second.x + second.width - first.x
            ) < 1e-8:
                edge_x = (
                    first.x + first.width
                    if abs(first.x + first.width - second.x) < 1e-8
                    else first.x
                )
                low = max(first.y, second.y)
                high = min(first.y + first.length, second.y + second.length)
                if high > low:
                    mid = (low + high) / 2
                    axis.plot(
                        [edge_x, edge_x],
                        [max(low, mid - 1.5), min(high, mid + 1.5)],
                        color="#dc2626",
                        linewidth=3,
                        zorder=5,
                    )
            elif abs(first.y + first.length - second.y) < 1e-8 or abs(
                second.y + second.length - first.y
            ) < 1e-8:
                edge_y = (
                    first.y + first.length
                    if abs(first.y + first.length - second.y) < 1e-8
                    else first.y
                )
                low = max(first.x, second.x)
                high = min(first.x + first.width, second.x + second.width)
                if high > low:
                    mid = (low + high) / 2
                    axis.plot(
                        [max(low, mid - 1.5), min(high, mid + 1.5)],
                        [edge_y, edge_y],
                        color="#dc2626",
                        linewidth=3,
                        zorder=5,
                    )

    entrance_room = actual_rooms.get(entrance_room_name or "")
    if entrance_room is not None and entrance_room.floor == floor_number:
        door_half_width = min(0.5, entrance_room.width / 2)
        door_half_length = min(0.5, entrance_room.length / 2)
        if entrance_side == "North":
            door_x, door_y = entrance_room.x + entrance_room.width / 2, entrance_room.y + entrance_room.length
            axis.plot([door_x - door_half_width, door_x + door_half_width], [door_y, door_y], color="#7c3aed", linewidth=4, zorder=7)
        elif entrance_side == "South":
            door_x, door_y = entrance_room.x + entrance_room.width / 2, entrance_room.y
            axis.plot([door_x - door_half_width, door_x + door_half_width], [door_y, door_y], color="#7c3aed", linewidth=4, zorder=7)
        elif entrance_side == "East":
            door_x, door_y = entrance_room.x + entrance_room.width, entrance_room.y + entrance_room.length / 2
            axis.plot([door_x, door_x], [door_y - door_half_length, door_y + door_half_length], color="#7c3aed", linewidth=4, zorder=7)
        else:
            door_x, door_y = entrance_room.x, entrance_room.y + entrance_room.length / 2
            axis.plot([door_x, door_x], [door_y - door_half_length, door_y + door_half_length], color="#7c3aed", linewidth=4, zorder=7)
        axis.annotate(
            f"Main entrance · {entrance_room.name}",
            (door_x, door_y),
            xytext=(7, 8),
            textcoords="offset points",
            fontsize=8,
            color="#6d28d9",
        )
        if floor_number == 1:
            axis.plot(
                [pedestrian_gate_x, door_x],
                [pedestrian_gate_y, door_y],
                linestyle=":",
                color="#2563eb",
                alpha=0.7,
                linewidth=1.3,
                zorder=1,
            )

    if floor_number == 1 and parking is not None:
        axis.plot(
            [gate_x, parking.x + parking.width / 2],
            [gate_y, parking.y + parking.length / 2],
            linestyle="--",
            color="#b45309",
            alpha=0.65,
            linewidth=1.2,
            zorder=1,
        )

    axis.legend(
        handles=[
            Patch(facecolor="#dcfce7", edgecolor="#15803d", hatch="..", label="Buildable area"),
            Patch(facecolor="#dbeafe", edgecolor="#1d4ed8", hatch="///", label="Staircase shaft"),
            Patch(facecolor="#fef3c7", edgecolor="#92400e", hatch="xx", label="Parking"),
            Line2D([0], [0], marker="s", color="w", markerfacecolor="#b45309", label="Vehicle gate", markersize=8),
            Line2D([0], [0], marker="^", color="w", markerfacecolor="#1d4ed8", label="Pedestrian gate", markersize=8),
            Line2D([0], [0], color="#dc2626", linewidth=3, label="Shared edge / door symbol (conceptual)"),
            Line2D([0], [0], color="#7c3aed", linewidth=3, label="Main entrance"),
            Line2D([0], [0], color="#2563eb", linestyle=":", linewidth=1.5, label="Pedestrian route (conceptual)"),
        ],
        fontsize=7,
        loc="upper right",
        framealpha=0.92,
    )
    axis.set_xticks(range(0, int(site_width) + 1, max(1, int(site_width // 10) or 1)))
    axis.set_yticks(range(0, int(site_length) + 1, max(1, int(site_length // 10) or 1)))
    axis.grid(color="#d9e0e8", linewidth=0.7, alpha=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)
    figure.tight_layout()
    return figure
