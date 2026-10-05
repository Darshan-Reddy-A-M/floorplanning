"""Streamlit interface for the architectural test-fit prototype."""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from testfit.defaults import DEFAULT_RELATIONSHIPS, DEFAULT_ROOMS
from testfit.optimizer import (
    MIN_ATTACHED_EDGE,
    RELATIONSHIP_KINDS,
    Room,
    RoomRelationship,
    STACKED_DISTANCE_THRESHOLD_M,
    calculate_metrics,
    solve_layout,
)
from testfit.visualization import create_floor_plan
from testfit.planning import (
    BUILDING_TYPES,
    PARKING_DEFAULT_FEET,
    STAIRCASE_DEFAULT_FEET,
    feet_to_meters,
    floor_label,
    meters_to_feet,
    planning_suggestions,
    recommend_room_program,
    setback_bounds_feet,
    select_entrance_room,
    square_meters_to_feet,
)

st.set_page_config(
    page_title="Architectural Test-Fit Generator",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container { max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem; }
      [data-testid="stMetric"] {
        background: #f6f8fb; border: 1px solid #e7ebf1;
        border-radius: 12px; padding: 16px 18px;
      }
      [data-testid="stMetricLabel"] { color: #586579; }
      div[data-testid="stAlert"] { border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.caption("Preliminary residential planning · CP-SAT")
st.title("Architectural Test-Fit Generator")
st.caption(
    "Explore a preliminary room program and floor plan. Dimensions are entered "
    "in feet; the CP-SAT solver uses metric units internally."
)
st.info(
    "Preliminary planning only — not professional architectural approval or "
    "code-certified design. Verify dimensions, setbacks, and local regulations "
    "with a qualified architect."
)

with st.sidebar:
    st.header("Site dimensions")
    site_width_ft = st.number_input(
        "Site width (ft)", min_value=1.0, max_value=5000.0, value=60.0, step=1.0
    )
    site_length_ft = st.number_input(
        "Site length (ft)", min_value=1.0, max_value=5000.0, value=50.0, step=1.0
    )
    road_access = st.selectbox(
        "Road / site access",
        options=["North", "South", "East", "West"],
        index=1,
    )
    front_rear_limit_ft = (
        site_width_ft if road_access in {"East", "West"} else site_length_ft
    )
    side_setback_limit_ft = (
        site_length_ft if road_access in {"East", "West"} else site_width_ft
    )
    with st.expander("Preliminary planning setbacks"):
        st.caption("Preliminary planning setbacks — not code-certified.")
        front_setback_ft = st.number_input(
            "Front setback (ft)", min_value=0.0, max_value=front_rear_limit_ft, value=0.0, step=1.0
        )
        rear_setback_ft = st.number_input(
            "Rear setback (ft)", min_value=0.0, max_value=front_rear_limit_ft, value=0.0, step=1.0
        )
        left_setback_ft = st.number_input(
            "Left setback (ft)", min_value=0.0, max_value=side_setback_limit_ft, value=0.0, step=1.0
        )
        right_setback_ft = st.number_input(
            "Right setback (ft)", min_value=0.0, max_value=side_setback_limit_ft, value=0.0, step=1.0
        )
    st.divider()
    st.header("Building configuration")
    building_type = st.selectbox(
        "Building type",
        options=BUILDING_TYPES,
        help=(
            "Single-family: one household. Duplex: one home over multiple floors. "
            "Rental / Apartment: independent units with shared circulation. "
            "Custom: your room program controls the layout."
        ),
    )
    number_of_floors = st.selectbox("Number of floors", options=[1, 2, 3, 4, 5], index=0)
    units_per_floor = 1
    if building_type in {
        "Rental / Multi-Unit Building",
        "Apartment / Multi-Unit Residential",
    }:
        units_per_floor = st.selectbox("Units per floor", options=[1, 2, 3, 4], index=0)
    parking_type = st.selectbox(
        "Parking", options=["No parking", "1 car", "2 cars"], index=0
    )
    if parking_type == "No parking":
        parking_width_ft = None
        parking_length_ft = None
    else:
        default_parking_width, default_parking_length = PARKING_DEFAULT_FEET[parking_type]
        parking_width_ft = st.number_input(
            "Parking width (ft)",
            min_value=1.0,
            max_value=200.0,
            value=default_parking_width,
            step=0.5,
            key=f"parking_width_{parking_type}",
        )
        parking_length_ft = st.number_input(
            "Parking length (ft)",
            min_value=1.0,
            max_value=200.0,
            value=default_parking_length,
            step=0.5,
            key=f"parking_length_{parking_type}",
        )
    entrance_side = st.selectbox(
        "Main entrance side",
        options=["Auto (road side)", "North", "South", "East", "West"],
        index=0,
    )
    if entrance_side == "Auto (road side)":
        entrance_side = road_access
    staircase_width_ft = STAIRCASE_DEFAULT_FEET[0]
    staircase_length_ft = STAIRCASE_DEFAULT_FEET[1]
    if number_of_floors > 1:
        with st.expander("Staircase shaft"):
            staircase_width_ft = st.number_input(
                "Staircase width (ft)", min_value=1.0, max_value=100.0,
                value=STAIRCASE_DEFAULT_FEET[0], step=0.5
            )
            staircase_length_ft = st.number_input(
                "Staircase length (ft)", min_value=1.0, max_value=100.0,
                value=STAIRCASE_DEFAULT_FEET[1], step=0.5
            )

site_width = feet_to_meters(site_width_ft)
site_length = feet_to_meters(site_length_ft)
parking_width = None if parking_width_ft is None else feet_to_meters(parking_width_ft)
parking_length = None if parking_length_ft is None else feet_to_meters(parking_length_ft)
staircase_width = feet_to_meters(staircase_width_ft)
staircase_length = feet_to_meters(staircase_length_ft)
try:
    buildable_bounds_ft = setback_bounds_feet(
        site_width_ft, site_length_ft, road_access,
        front_setback_ft, rear_setback_ft, left_setback_ft, right_setback_ft,
    )
except ValueError as error:
    st.error(str(error))
    st.stop()
buildable_bounds = tuple(feet_to_meters(value) for value in buildable_bounds_ft)
buildable_width_ft = buildable_bounds_ft[2] - buildable_bounds_ft[0]
buildable_length_ft = buildable_bounds_ft[3] - buildable_bounds_ft[1]
buildable_area_ft2 = buildable_width_ft * buildable_length_ft
site_area_ft2 = site_width_ft * site_length_ft
st.caption("User units: feet | Solver units: metric internally")

overview_columns = st.columns(4)
overview_columns[0].metric("Site", f"{site_width_ft:.1f} × {site_length_ft:.1f} ft")
overview_columns[1].metric("Total site area", f"{site_area_ft2:,.0f} sq ft")
overview_columns[2].metric("Buildable area / floor", f"{buildable_area_ft2:,.0f} sq ft")
overview_columns[3].metric(
    "Remaining open area", f"{site_area_ft2 - buildable_area_ft2:,.0f} sq ft"
)

if (
    "room_rows" not in st.session_state
    or "Width (ft)" not in st.session_state.room_rows.columns
):
    st.session_state.room_rows = pd.DataFrame(
        [
            {
                "Room": room.name,
                "Floor": room.floor,
                "Width (ft)": meters_to_feet(room.width),
                "Length (ft)": meters_to_feet(room.length),
                "Required": True,
            }
            for room in DEFAULT_ROOMS
        ]
    )
if "relationship_rows" not in st.session_state:
    st.session_state.relationship_rows = pd.DataFrame(
        [
            {
                "Room A": relationship.room_a,
                "Room B": relationship.room_b,
                "Relationship": relationship.kind,
            }
            for relationship in DEFAULT_RELATIONSHIPS
        ]
    )

if (
    building_type == "Custom"
    and st.session_state.get("planning_mode") != "Custom Room Requirements"
):
    st.session_state.planning_mode = "Custom Room Requirements"

planning_mode = st.radio(
    "Room planning mode",
    options=["Automatic Room Recommendation", "Custom Room Requirements"],
    horizontal=True,
    key="planning_mode",
)

recommended_rooms, recommended_relationships, estimated_floor_area_ft2 = (
    recommend_room_program(
        buildable_bounds_ft=buildable_bounds_ft,
        number_of_floors=number_of_floors,
        building_type=building_type,
        units_per_floor=units_per_floor,
        parking_area_ft2=(
            parking_width_ft * parking_length_ft
            if parking_width_ft is not None and parking_length_ft is not None
            else 0.0
        ),
        staircase_size_ft=(staircase_width_ft, staircase_length_ft),
    )
)
recommended_frame = pd.DataFrame(
    [
        {
            "Room": room.name,
            "Floor": room.floor,
            "Width (ft)": round(meters_to_feet(room.width), 1),
            "Length (ft)": round(meters_to_feet(room.length), 1),
            "Required": True,
        }
        for room in recommended_rooms
    ]
)
program_signature = (
    tuple(round(value, 2) for value in buildable_bounds_ft),
    number_of_floors,
    building_type,
    units_per_floor,
    parking_type,
    parking_width_ft,
    parking_length_ft,
    staircase_width_ft,
    staircase_length_ft,
)
bedroom_count = sum("Bedroom" in room.name for room in recommended_rooms)
bathroom_count = sum("Bathroom" in room.name for room in recommended_rooms)
if building_type == "Custom":
    st.subheader("Custom Room Requirements")
elif planning_mode == "Automatic Room Recommendation":
    st.subheader("Recommended Room Program")
else:
    st.subheader("Example Program · edit your requirements below")
estimated_usable_ft2 = max(
    0.0,
    (
        estimated_floor_area_ft2 * number_of_floors
        - (parking_width_ft or 0) * (parking_length_ft or 0)
        - staircase_width_ft
        * staircase_length_ft
        * (number_of_floors if number_of_floors > 1 else 0)
    )
    * 0.82,
)
st.caption(
    f"Estimated capacity: about {estimated_floor_area_ft2:,.0f} sq ft per floor; "
    f"approximately {estimated_usable_ft2:,.0f} sq ft usable across "
    f"{number_of_floors} floor(s), allowing 18% for circulation."
)
st.caption(
    f"Recommended: {bedroom_count} bedroom(s), {bathroom_count} bathroom(s), "
    f"{len(recommended_rooms)} total spaces. Building type: {building_type}; "
    f"parking: {parking_type}; floors: {number_of_floors}."
)
if building_type != "Custom":
    st.caption(
        f"Recommended: {bedroom_count} bedroom(s), {bathroom_count} bathroom(s), "
        f"{len(recommended_rooms)} total spaces. Building type: {building_type}; "
        f"parking: {parking_type}; floors: {number_of_floors}."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Room": room.name,
                    "Floor": floor_label(room.floor),
                    "Size": (
                        f"{meters_to_feet(room.width):.1f} × "
                        f"{meters_to_feet(room.length):.1f} ft"
                    ),
                }
                for room in recommended_rooms
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    recommended_room_area_ft2 = square_meters_to_feet(
        sum(room.width * room.length for room in recommended_rooms)
    )
    if recommended_room_area_ft2 > estimated_usable_ft2:
        st.warning(
            "Recommended program may not fit within the estimated usable area. "
            "Review the room sizes, reduce the program, or increase the floor count."
        )
    for suggestion in planning_suggestions(
        floor_area_ft2=estimated_floor_area_ft2,
        number_of_floors=number_of_floors,
        parking_type=parking_type,
        bedroom_count=bedroom_count,
    ):
        st.info(suggestion)
    st.caption(
        "Preliminary automated suggestions — verify with a qualified architect and "
        "applicable local regulations."
    )
else:
    st.caption(
        "Custom building type selected: the room table controls the layout; "
        "no automatic room program is assumed."
    )

if planning_mode == "Automatic Room Recommendation":
    action_columns = st.columns(2)
    if action_columns[0].button("Accept Recommendation", type="primary", width="stretch"):
        st.session_state.accepted_program_signature = program_signature
        st.session_state.accepted_room_rows = recommended_frame.copy()
        st.session_state.accepted_relationships = pd.DataFrame(
            [
                {
                    "Room A": relationship.room_a,
                    "Room B": relationship.room_b,
                    "Relationship": relationship.kind,
                }
                for relationship in recommended_relationships
            ]
        )
        st.rerun()
    if action_columns[1].button("Customize Rooms", width="stretch"):
        st.session_state.room_rows = recommended_frame.copy()
        st.session_state.relationship_rows = pd.DataFrame(
            [
                {
                    "Room A": relationship.room_a,
                    "Room B": relationship.room_b,
                    "Relationship": relationship.kind,
                }
                for relationship in recommended_relationships
            ]
        )
        st.session_state.planning_mode = "Custom Room Requirements"
        st.rerun()
    recommendation_accepted = (
        st.session_state.get("accepted_program_signature") == program_signature
    )
    if recommendation_accepted:
        st.success("Recommendation accepted. Generate the test-fit when ready.")
        edited_rooms = st.session_state.accepted_room_rows
        edited_relationships = st.session_state.accepted_relationships
    else:
        st.info("Accept this recommendation or customize the rooms before generating.")
        edited_rooms = recommended_frame
        edited_relationships = pd.DataFrame(
            [
                {
                    "Room A": relationship.room_a,
                    "Room B": relationship.room_b,
                    "Relationship": relationship.kind,
                }
                for relationship in recommended_relationships
            ]
        )
else:
    recommendation_accepted = True
    st.write("Room dimensions are fixed inputs; the solver does not resize rooms.")
    edited_rooms = st.data_editor(
        st.session_state.room_rows,
        key="room_editor",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "Room": st.column_config.TextColumn("Room name", required=False),
            "Floor": st.column_config.SelectboxColumn(
                "Floor", options=list(range(1, number_of_floors + 1)),
                required=True, default=1,
            ),
            "Width (ft)": st.column_config.NumberColumn(
                "Width (ft)", min_value=0.1, max_value=10000.0, step=0.5, format="%.1f"
            ),
            "Length (ft)": st.column_config.NumberColumn(
                "Length (ft)", min_value=0.1, max_value=10000.0, step=0.5, format="%.1f"
            ),
            "Required": st.column_config.CheckboxColumn("Required", default=True),
        },
    )
    st.session_state.room_rows = edited_rooms.copy()
    st.subheader("Room relationships")
    st.write(
        f"**Hard:** ATTACHED requires at least {meters_to_feet(MIN_ATTACHED_EDGE):.1f} ft "
        "of shared edge; ADJACENT requires a positive-length shared edge. "
        "**Soft:** NEAR, PREFERRED, and STACKED remain optimization preferences."
    )
    edited_relationships = st.data_editor(
        st.session_state.relationship_rows,
        key="relationship_editor",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "Room A": st.column_config.TextColumn("Room A"),
            "Room B": st.column_config.TextColumn("Room B"),
            "Relationship": st.column_config.SelectboxColumn(
                "Relationship", options=sorted(RELATIONSHIP_KINDS), required=False
            ),
        },
    )
    st.session_state.relationship_rows = edited_relationships.copy()

generate = st.button(
    "Generate test-fit",
    type="primary",
    width="stretch",
    disabled=(planning_mode == "Automatic Room Recommendation" and not recommendation_accepted),
)


def parse_rooms(frame: pd.DataFrame, floor_count: int) -> list[Room]:
    """Validate edited rows and skip entirely blank rows from the dynamic editor."""
    rooms: list[Room] = []
    errors: list[str] = []
    names: set[str] = set()

    for row_number, row in frame.iterrows():
        raw_name = row.get("Room")
        raw_floor = row.get("Floor", 1)
        raw_width = row.get("Width (ft)")
        raw_length = row.get("Length (ft)")
        name = "" if pd.isna(raw_name) else str(raw_name).strip()
        floor_blank = pd.isna(raw_floor)
        width_blank = pd.isna(raw_width)
        length_blank = pd.isna(raw_length)

        if not name and width_blank and length_blank:
            continue
        if not name or floor_blank or width_blank or length_blank:
            errors.append(
                f"Row {row_number + 1}: enter a name, floor, width, and length."
            )
            continue
        if name in names:
            errors.append(f"Room names must be unique; {name!r} appears more than once.")
            continue
        names.add(name)

        try:
            floor = int(raw_floor)
            width = float(raw_width)
            length = float(raw_length)
        except (TypeError, ValueError, OverflowError):
            errors.append(
                f"Row {row_number + 1}: floor must be an integer; width and length must be numbers."
            )
            continue

        if isinstance(raw_floor, bool) or floor != raw_floor or not 1 <= floor <= floor_count:
            errors.append(
                f"Row {row_number + 1}: floor must be between 1 and {floor_count}."
            )
            continue
        if not math.isfinite(width) or not math.isfinite(length) or width <= 0 or length <= 0:
            errors.append(f"Row {row_number + 1}: width and length must be greater than zero.")
            continue
        rooms.append(
            Room(
                name=name,
                width=feet_to_meters(width),
                length=feet_to_meters(length),
                floor=floor,
            )
        )

    if errors:
        raise ValueError(" ".join(errors))
    if not rooms:
        raise ValueError("Add at least one room to generate a test-fit.")
    return rooms


def parse_relationships(
    frame: pd.DataFrame, rooms: list[Room]
) -> list[RoomRelationship]:
    """Validate relationship rows and ensure they refer to existing room names."""
    room_by_name = {room.name: room for room in rooms}
    room_names = set(room_by_name)
    relationships: list[RoomRelationship] = []
    errors: list[str] = []
    seen_pairs: set[tuple[str, str, str]] = set()

    for row_number, row in frame.iterrows():
        raw_room_a = row.get("Room A")
        raw_room_b = row.get("Room B")
        raw_kind = row.get("Relationship")
        room_a = "" if pd.isna(raw_room_a) else str(raw_room_a).strip()
        room_b = "" if pd.isna(raw_room_b) else str(raw_room_b).strip()
        kind = "" if pd.isna(raw_kind) else str(raw_kind).strip().upper()

        if not room_a and not room_b and not kind:
            continue
        if not room_a or not room_b or not kind:
            errors.append(
                f"Relationship row {row_number + 1}: enter Room A, Room B, and a relationship type."
            )
            continue
        if room_a == room_b:
            errors.append(
                f"Relationship row {row_number + 1}: select two different rooms."
            )
            continue
        if room_a not in room_names or room_b not in room_names:
            errors.append(
                f"Relationship row {row_number + 1}: both rooms must exist in the Rooms table."
            )
            continue
        if kind not in RELATIONSHIP_KINDS:
            errors.append(
                f"Relationship row {row_number + 1}: choose ATTACHED, ADJACENT, NEAR, PREFERRED, or STACKED."
            )
            continue
        floor_a = room_by_name[room_a].floor
        floor_b = room_by_name[room_b].floor
        if kind == "STACKED" and abs(floor_a - floor_b) != 1:
            errors.append(
                f"Relationship row {row_number + 1}: STACKED requires rooms on adjacent floors."
            )
            continue
        if kind != "STACKED" and floor_a != floor_b:
            errors.append(
                f"Relationship row {row_number + 1}: {kind} requires both rooms on the same floor."
            )
            continue

        pair = (*sorted((room_a, room_b)), kind)
        if pair in seen_pairs:
            errors.append(
                f"Relationship row {row_number + 1}: this room pair already has this relationship type."
            )
            continue
        seen_pairs.add(pair)
        relationships.append(RoomRelationship(room_a, room_b, kind))

    if errors:
        raise ValueError(" ".join(errors))
    return relationships


try:
    rooms = parse_rooms(edited_rooms, number_of_floors)
    relationships = parse_relationships(edited_relationships, rooms)
    optional_names = set()
    if "Required" in edited_rooms:
        for _, row in edited_rooms.iterrows():
            name = "" if pd.isna(row.get("Room")) else str(row.get("Room")).strip()
            required = row.get("Required", True)
            if name and not pd.isna(required) and str(required).casefold() in {"false", "0", "no"}:
                optional_names.add(name)
    input_signature = (
        round(float(site_width_ft), 1),
        round(float(site_length_ft), 1),
        tuple(round(float(value), 1) for value in buildable_bounds_ft),
        number_of_floors,
        building_type,
        units_per_floor,
        road_access,
        entrance_side,
        parking_type,
        None if parking_width_ft is None else round(float(parking_width_ft), 1),
        None if parking_length_ft is None else round(float(parking_length_ft), 1),
        round(float(staircase_width_ft), 1),
        round(float(staircase_length_ft), 1),
        tuple(
            (
                room.name,
                room.floor,
                round(meters_to_feet(room.width), 1),
                round(meters_to_feet(room.length), 1),
                room.name not in optional_names,
            )
            for room in rooms
        ),
        tuple(
            (relationship.room_a, relationship.room_b, relationship.kind)
            for relationship in relationships
        ),
    )

    if generate:
        with st.spinner("Searching for a valid room arrangement..."):
            result = solve_layout(
                site_width,
                site_length,
                rooms,
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
        omitted_optional = []
        active_relationships = relationships
        if result.status == "INFEASIBLE" and optional_names:
            required_rooms = [room for room in rooms if room.name not in optional_names]
            if required_rooms:
                required_names = {room.name for room in required_rooms}
                required_relationships = [
                    relationship
                    for relationship in relationships
                    if relationship.room_a in required_names
                    and relationship.room_b in required_names
                ]
                required_result = solve_layout(
                    site_width,
                    site_length,
                    required_rooms,
                    relationships=required_relationships,
                    number_of_floors=number_of_floors,
                    parking_type=parking_type,
                    parking_width=parking_width,
                    parking_length=parking_length,
                    road_access=road_access,
                    staircase_width=staircase_width,
                    staircase_length=staircase_length,
                    buildable_bounds=buildable_bounds,
                )
                if required_result.placements:
                    result = required_result
                    active_relationships = required_relationships
                    omitted_optional = sorted(optional_names)
        st.session_state.input_signature = input_signature
        st.session_state.layout_result = result
        st.session_state.layout_rooms = [
            room for room in rooms if room.name not in omitted_optional
        ]
        st.session_state.layout_relationships = active_relationships
        st.session_state.layout_site = (float(site_width), float(site_length))
        st.session_state.omitted_optional_rooms = omitted_optional

    result = (
        st.session_state.get("layout_result")
        if st.session_state.get("input_signature") == input_signature
        else None
    )
    if result is not None and st.session_state.get("omitted_optional_rooms"):
        st.warning(
            "These optional rooms did not fit and were left out of this test-fit: "
            + ", ".join(st.session_state.omitted_optional_rooms)
        )
    if result is None and st.session_state.get("layout_result") is not None:
        st.warning("Inputs changed since the last test-fit. Generate a new plan to update the results.")
    if result is None:
        st.info("Accept the recommendation or configure custom rooms, then generate a test-fit.")
    elif result.placements:
        active_relationships = st.session_state.get(
            "layout_relationships", relationships
        )
        metrics = calculate_metrics(
            site_width,
            site_length,
            result.placements,
            active_relationships,
            number_of_floors=result.number_of_floors,
            parking=result.parking,
            staircases=result.staircases,
        )
        st.divider()
        st.subheader("Test-fit overview")
        st.write(
            f"**Building type:** {building_type} · **Floors:** {number_of_floors} · "
            f"**Parking:** {parking_type} · **Site:** "
            f"{site_width_ft:.1f} × {site_length_ft:.1f} ft"
        )
        metric_columns = st.columns(4)
        metric_columns[0].metric("Total site area", f"{site_area_ft2:,.0f} sq ft")
        metric_columns[1].metric(
            "Buildable area", f"{buildable_area_ft2:,.0f} sq ft / floor"
        )
        metric_columns[2].metric(
            "Remaining open area",
            f"{site_area_ft2 - buildable_area_ft2:,.0f} sq ft",
            help="Site area outside the buildable rectangle, before parking allocation.",
        )
        metric_columns[3].metric(
            "Total room area",
            f"{square_meters_to_feet(metrics.total_room_area):,.0f} sq ft",
            help="Total room area across all generated floors; this is not site coverage.",
        )

        actual_bedrooms = sum("bedroom" in p.name.casefold() for p in result.placements)
        actual_bathrooms = sum("bathroom" in p.name.casefold() for p in result.placements)
        stair_area_across_floors = sum(
            stair.width * stair.length
            * ((stair.floor_end or stair.floor) - stair.floor + 1)
            for stair in result.staircases
        )
        allocation_columns = st.columns(6)
        allocation_columns[0].metric("Number of floors", metrics.number_of_floors)
        allocation_columns[1].metric("Bedrooms", actual_bedrooms)
        allocation_columns[2].metric("Bathrooms", actual_bathrooms)
        allocation_columns[3].metric(
            "Building footprint",
            f"{square_meters_to_feet(metrics.building_footprint_area):,.0f} sq ft",
        )
        allocation_columns[4].metric(
            "Parking area", f"{square_meters_to_feet(metrics.parking_area):,.0f} sq ft"
        )
        allocation_columns[5].metric(
            "Total stair area",
            f"{square_meters_to_feet(stair_area_across_floors):,.0f} sq ft",
            help="Shared staircase-shaft area counted on every floor it serves.",
        )

        site_columns = st.columns(2)
        site_columns[0].metric(
            "Allocated site footprint",
            f"{square_meters_to_feet(metrics.total_allocated_site_area):,.0f} sq ft",
            help=(
                "Footprint union of the building, staircase shaft, and parking; "
                "upper floors are not counted again as additional land area."
            ),
        )
        site_columns[1].metric(
            "Site utilization", f"{metrics.site_utilization_percent:.1f}%"
        )

        floor_rows = [
            {
                "Floor": floor_label(floor),
                "Buildable area (sq ft)": round(buildable_area_ft2),
                "Room area (sq ft)": round(
                    square_meters_to_feet(metrics.floor_room_area.get(floor, 0.0))
                ),
                "Circulation / stair area (sq ft)": round(
                    square_meters_to_feet(
                        sum(
                            stair.width * stair.length
                            for stair in result.staircases
                            if stair.floor <= floor <= (stair.floor_end or stair.floor)
                        )
                    )
                ),
                "Utilization": (
                    f"{(
                        square_meters_to_feet(metrics.floor_room_area.get(floor, 0.0))
                        + square_meters_to_feet(sum(
                            stair.width * stair.length
                            for stair in result.staircases
                            if stair.floor <= floor <= (stair.floor_end or stair.floor)
                        ))
                    ) / buildable_area_ft2 * 100:.1f}%"
                    if buildable_area_ft2
                    else "—"
                ),
                "Unused buildable area (sq ft)": round(
                    max(
                        0.0,
                        buildable_area_ft2
                        - square_meters_to_feet(metrics.floor_room_area.get(floor, 0.0))
                        - square_meters_to_feet(
                            sum(
                                stair.width * stair.length
                                for stair in result.staircases
                                if stair.floor <= floor <= (stair.floor_end or stair.floor)
                            )
                        ),
                    )
                ),
            }
            for floor in range(1, metrics.number_of_floors + 1)
        ]
        st.subheader("Per-floor metrics")
        st.dataframe(pd.DataFrame(floor_rows), hide_index=True, width="stretch")

        compactness_columns = st.columns(3)
        compactness_columns[0].metric(
            "Occupied bounding-box dimensions",
            f"{meters_to_feet(metrics.occupied_width):.1f} × "
            f"{meters_to_feet(metrics.occupied_length):.1f} ft",
        )
        compactness_columns[1].metric(
            "Occupied bounding-box area",
            f"{square_meters_to_feet(metrics.occupied_bbox_area):,.0f} sq ft",
        )
        compactness_columns[2].metric(
            "Layout compactness",
            f"{metrics.layout_compactness_percent:.1f}%",
            help="Total room area divided by the occupied bounding-box area.",
        )

        check_columns = st.columns(2)
        check_columns[0].metric("Room overlaps", metrics.overlap_count)
        check_columns[1].metric("Boundary violations", metrics.boundary_violation_count)

        st.subheader("Building elements")
        element_columns = st.columns(2)
        if result.parking is None:
            element_columns[0].metric("Parking", "No parking")
        else:
            element_columns[0].metric(
                "Parking",
                f"{result.parking_type} · "
                f"{square_meters_to_feet(metrics.parking_area):,.0f} sq ft",
                delta=(
                    f"at ({meters_to_feet(result.parking.x):.1f}, "
                    f"{meters_to_feet(result.parking.y):.1f}) ft"
                ),
            )
        if result.staircases:
            stair = result.staircases[0]
            element_columns[1].metric(
                "Staircase",
                f"{meters_to_feet(stair.width):.1f} × "
                f"{meters_to_feet(stair.length):.1f} ft",
                delta=(
                    f"{square_meters_to_feet(metrics.staircase_area):,.0f} sq ft "
                    "shared shaft footprint"
                ),
                help=(
                    "The staircase shaft occupies the same footprint on every floor "
                    "and connects each adjacent pair of floors."
                ),
            )
        else:
            element_columns[1].metric("Staircase", "Not required")

        hard_relationship_columns = st.columns(2)
        hard_relationship_columns[0].metric(
            "ATTACHED satisfied",
            f"{metrics.attached_satisfied} / {metrics.attached_total}",
        )
        hard_relationship_columns[1].metric(
            "ADJACENT satisfied",
            f"{metrics.adjacent_satisfied} / {metrics.adjacent_total}",
        )

        soft_relationship_columns = st.columns(3)
        soft_relationship_columns[0].metric(
            "NEAR satisfied",
            f"{metrics.near_satisfied} / {metrics.near_total}",
            help=(
                f"NEAR distance total from the generated coordinates: "
                f"{meters_to_feet(metrics.near_distance_total):.1f} ft. A relationship "
                "counts as satisfied when its rectilinear gap is at most 3.3 ft."
            ),
        )
        soft_relationship_columns[1].metric(
            "PREFERRED satisfied",
            f"{metrics.preferred_satisfied} / {metrics.preferred_total}",
            help=(
                f"Actual preferred excess-distance penalty: "
                f"{meters_to_feet(metrics.preferred_penalty_total):.1f} ft beyond "
                "the 3.3 ft threshold."
            ),
        )
        soft_relationship_columns[2].metric(
            "STACKED satisfied",
            f"{metrics.stacked_satisfied} / {metrics.stacked_total}",
            help=(
                f"Actual adjacent-floor room-center distance total: "
                f"{meters_to_feet(metrics.stacked_center_distance_total):.1f} ft. "
                f"STACKED counts as satisfied within "
                f"{meters_to_feet(STACKED_DISTANCE_THRESHOLD_M):.1f} ft."
            ),
        )

        soft_summary_columns = st.columns(2)
        soft_summary_columns[0].metric(
            "Soft penalty / distance",
            f"{meters_to_feet(metrics.soft_penalty_distance_total):.1f} ft",
            help=(
                "Sum of NEAR distances, PREFERRED excess distance beyond 3.3 ft, "
                "and STACKED room-center distances."
            ),
        )
        soft_summary_columns[1].metric(
            "Relationship satisfaction",
            f"{metrics.relationship_satisfaction_percent:.1f}%",
        )

        if result.status == "OPTIMAL":
            st.success(
                "A valid arrangement was found; all hard constraints are satisfied "
                "and every optimization priority stage was proven optimal."
            )
        else:
            st.info(
                "A valid arrangement satisfying all hard constraints was found. "
                "Some compactness or soft-relationship objective stages were not proven "
                "optimal before the time limit."
            )

        st.subheader("Floor plans")
        st.caption(
            "The main door marker is drawn on a room boundary at the selected exterior side. "
            "Dashed pedestrian and driveway lines are conceptual; clear access and door "
            "swings are not solver-verified."
        )
        entrance_room = select_entrance_room(result.placements, entrance_side)
        if entrance_room is None:
            st.warning(
                "No non-bathroom room was placed on the ground floor, so a main-door "
                "marker could not be generated. Add a ground-floor foyer or living room."
            )

        def display_placement(placement):
            from testfit.optimizer import Placement

            return Placement(
                name=placement.name,
                x=meters_to_feet(placement.x),
                y=meters_to_feet(placement.y),
                width=meters_to_feet(placement.width),
                length=meters_to_feet(placement.length),
                floor=placement.floor,
                floor_end=placement.floor_end,
            )

        display_bounds = tuple(meters_to_feet(value) for value in buildable_bounds)
        for floor in range(1, result.number_of_floors + 1):
            floor_plan = create_floor_plan(
                site_width_ft,
                site_length_ft,
                [
                    display_placement(placement)
                    for placement in result.placements
                    if placement.floor == floor
                ],
                floor_number=floor,
                parking=(
                    display_placement(result.parking)
                    if result.parking is not None
                    else None
                ),
                staircases=[display_placement(stair) for stair in result.staircases],
                buildable_bounds=display_bounds,
                road_access=road_access,
                entrance_room_name=(
                    entrance_room.name if entrance_room is not None else None
                ),
                entrance_side=entrance_side,
                relationships=active_relationships,
                unit_label="ft",
            )
            st.pyplot(floor_plan, width="stretch")
    else:
        st.divider()
        st.subheader("Test-fit overview")
        input_area = sum(room.width * room.length for room in rooms)
        columns = st.columns(4)
        columns[0].metric("Total site area", f"{site_area_ft2:,.0f} sq ft")
        columns[1].metric(
            "Requested room area", f"{square_meters_to_feet(input_area):,.0f} sq ft"
        )
        columns[2].metric(
            "Unused site area",
            "—",
            help="No valid placement exists, so allocated and unused site area cannot be measured.",
        )
        columns[3].metric(
            "Room area / site area",
            f"{(input_area / (site_width * site_length) * 100):.1f}%"
            if site_width * site_length
            else "—",
            help="Requested room area across floors divided by site area; this is not site utilization.",
        )
        st.caption(
            f"Requested configuration: {number_of_floors} floor(s), "
            f"{parking_type.lower()} parking, road access on the {road_access.lower()} side."
        )
        compactness_columns = st.columns(3)
        compactness_columns[0].metric(
            "Occupied bounding-box dimensions",
            "—",
            help="No valid room coordinates exist to calculate the occupied bounds.",
        )
        compactness_columns[1].metric(
            "Occupied bounding-box area",
            "—",
            help="No valid room coordinates exist to calculate the occupied bounds.",
        )
        compactness_columns[2].metric(
            "Layout compactness",
            "—",
            help="No valid room coordinates exist to calculate compactness.",
        )
        st.metric("Room overlaps", "—", help="No valid arrangement exists to audit.")
        st.metric("Boundary violations", "—", help="No valid arrangement exists to audit.")
        relationship_totals = {
            kind: sum(relationship.kind == kind for relationship in relationships)
            for kind in RELATIONSHIP_KINDS
        }
        hard_relationship_columns = st.columns(2)
        hard_relationship_columns[0].metric(
            "ATTACHED satisfied",
            f"— / {relationship_totals['ATTACHED']}",
        )
        hard_relationship_columns[1].metric(
            "ADJACENT satisfied",
            f"— / {relationship_totals['ADJACENT']}",
        )
        soft_relationship_columns = st.columns(3)
        soft_relationship_columns[0].metric(
            "NEAR satisfied", f"— / {relationship_totals['NEAR']}"
        )
        soft_relationship_columns[1].metric(
            "PREFERRED satisfied", f"— / {relationship_totals['PREFERRED']}"
        )
        soft_relationship_columns[2].metric(
            "STACKED satisfied", f"— / {relationship_totals['STACKED']}"
        )
        soft_summary_columns = st.columns(2)
        soft_summary_columns[0].metric("Soft penalty / distance", "—")
        soft_summary_columns[1].metric(
            "Relationship satisfaction",
            "—",
            help="No valid coordinates exist to check the relationships.",
        )
        st.error(
            "No valid arrangement was found. Check that every room fits within the site "
            "and that the room and relationship constraints can all be satisfied."
        )
        st.caption(
            "Program may not fit. Try reducing bedrooms or parking, increasing the "
            "number of floors (up to five), or switching to custom room requirements."
        )
        st.caption(f"Solver status: {result.status}. {result.message}")

except ValueError as error:
    st.error(str(error))