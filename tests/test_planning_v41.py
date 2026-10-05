import unittest

from testfit.optimizer import Placement, Room, solve_layout
from testfit.planning import (
    feet_area_to_square_meters,
    feet_to_meters,
    floor_label,
    meters_to_feet,
    recommend_room_program,
    setback_bounds_feet,
    select_entrance_room,
    square_meters_to_feet,
)


class PlanningV41Tests(unittest.TestCase):
    def test_feet_and_square_foot_conversions(self):
        self.assertAlmostEqual(feet_to_meters(1), 0.3048)
        self.assertAlmostEqual(meters_to_feet(0.3048), 1)
        self.assertAlmostEqual(feet_area_to_square_meters(10.7639104167), 1)
        self.assertAlmostEqual(square_meters_to_feet(1), 10.7639104167)

    def test_setbacks_resolve_against_the_selected_frontage(self):
        north_access = setback_bounds_feet(100, 80, "North", 10, 5, 7, 3)
        self.assertEqual(north_access, (3, 5, 93, 70))
        west_access = setback_bounds_feet(100, 80, "West", 10, 5, 7, 3)
        self.assertEqual(west_access, (10, 3, 95, 73))

    def test_setbacks_constrain_solver_rooms_to_buildable_rectangle(self):
        result = solve_layout(
            20,
            20,
            [Room("Test room", 2, 2)],
            buildable_bounds=(3, 4, 17, 16),
            time_limit_seconds=2,
        )
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        room = result.placements[0]
        self.assertGreaterEqual(room.x, 3)
        self.assertGreaterEqual(room.y, 4)
        self.assertLessEqual(room.x + room.width, 17)
        self.assertLessEqual(room.y + room.length, 16)

    def test_five_floor_plan_supports_repeated_xy_on_distinct_floors(self):
        rooms = [Room(f"Room {floor}", 1, 1, floor=floor) for floor in range(1, 6)]
        result = solve_layout(20, 20, rooms, number_of_floors=5, time_limit_seconds=5)
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(len(result.placements), 5)
        placements = {room.name: room for room in result.placements}
        self.assertAlmostEqual(placements["Room 1"].x, placements["Room 5"].x)
        self.assertAlmostEqual(placements["Room 1"].y, placements["Room 5"].y)
        self.assertEqual(len(result.staircases), 1)
        self.assertEqual(result.staircases[0].floor_end, 5)

    def test_recommendation_responds_to_site_size_and_floor_count(self):
        small, _, _ = recommend_room_program(
            buildable_bounds_ft=(0, 0, 20, 20),
            number_of_floors=1,
            building_type="Single-Family House",
        )
        larger, _, _ = recommend_room_program(
            buildable_bounds_ft=(0, 0, 40, 40),
            number_of_floors=1,
            building_type="Single-Family House",
        )
        multistory, _, _ = recommend_room_program(
            buildable_bounds_ft=(0, 0, 40, 40),
            number_of_floors=2,
            building_type="Single-Family House",
        )
        self.assertGreater(
            sum("Bedroom" in room.name for room in larger),
            sum("Bedroom" in room.name for room in small),
        )
        self.assertGreater(
            sum("Bedroom" in room.name for room in multistory),
            sum("Bedroom" in room.name for room in larger),
        )

    def test_four_floor_solver_supports_a_continuous_staircase(self):
        rooms = [Room(f"Room {floor}", 1, 1, floor=floor) for floor in range(1, 5)]
        result = solve_layout(20, 20, rooms, number_of_floors=4, time_limit_seconds=5)
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(result.number_of_floors, 4)
        self.assertEqual(result.staircases[0].floor_end, 4)

    def test_multifamily_recommendation_creates_units_on_selected_floors(self):
        rooms, relationships, _ = recommend_room_program(
            buildable_bounds_ft=(0, 0, 50, 50),
            number_of_floors=3,
            building_type="Rental / Multi-Unit Building",
            units_per_floor=2,
        )
        self.assertEqual(len(rooms), 3 * 2 * 4)
        self.assertEqual({room.floor for room in rooms}, {1, 2, 3})
        self.assertEqual(sum(item.kind == "ATTACHED" for item in relationships), 6)

    def test_floor_labels_are_human_readable(self):
        self.assertEqual(floor_label(1), "Ground Floor")
        self.assertEqual(floor_label(5), "Fourth Floor")

    def test_entrance_selection_uses_exterior_non_bathroom_room(self):
        rooms = [
            Placement("Bathroom", 0, 0, 4, 4, floor=1),
            Placement("Living Room", 0, 4, 6, 6, floor=1),
            Placement("Entry Foyer", 6, 0, 4, 4, floor=1),
        ]
        entrance = select_entrance_room(rooms, "North")
        self.assertEqual(entrance.name, "Living Room")
        self.assertIsNone(select_entrance_room([rooms[0]], "South"))


if __name__ == "__main__":
    unittest.main()
