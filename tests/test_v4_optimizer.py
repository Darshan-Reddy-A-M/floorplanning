import unittest

from matplotlib import pyplot as plt

from testfit.optimizer import (
    Placement,
    Room,
    RoomRelationship,
    calculate_metrics,
    solve_layout,
)
from testfit.visualization import create_floor_plan


class V4SolveLayoutTests(unittest.TestCase):
    def test_two_floor_geometry_is_independent_by_floor(self):
        rooms = [
            Room("Lower A", 2, 2, floor=1),
            Room("Lower B", 2, 2, floor=1),
            Room("Upper", 2, 2, floor=2),
        ]

        result = solve_layout(8, 8, rooms, number_of_floors=2, time_limit_seconds=2)

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        placed = {room.name: room for room in result.placements}
        self.assertNotEqual(
            (placed["Lower A"].x, placed["Lower A"].y),
            (placed["Lower B"].x, placed["Lower B"].y),
        )
        self.assertEqual(
            (placed["Lower A"].x, placed["Lower A"].y),
            (placed["Upper"].x, placed["Upper"].y),
        )
        self.assertEqual(result.number_of_floors, 2)

    def test_three_floor_layout_has_a_continuous_staircase_shaft(self):
        rooms = [
            Room("Ground", 2, 2, floor=1),
            Room("Middle", 2, 2, floor=2),
            Room("Top", 2, 2, floor=3),
        ]

        result = solve_layout(8, 8, rooms, number_of_floors=3, time_limit_seconds=2)

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(result.number_of_floors, 3)
        self.assertEqual(len(result.staircases), 1)
        staircase = result.staircases[0]
        self.assertEqual((staircase.floor, staircase.floor_end), (1, 3))
        self.assertEqual((staircase.width, staircase.length), (2, 4))
        metrics = calculate_metrics(
            8,
            8,
            result.placements,
            number_of_floors=3,
            staircases=result.staircases,
        )
        self.assertEqual(metrics.overlap_count, 0)
        self.assertEqual(metrics.boundary_violation_count, 0)
        self.assertEqual(metrics.staircase_area, 8)

    def test_one_and_two_car_parking_fit_inside_without_room_overlap(self):
        for parking_type, expected_area in (("1 car", 12.5), ("2 cars", 25.0)):
            with self.subTest(parking_type=parking_type):
                result = solve_layout(
                    10,
                    10,
                    [Room("Room", 3, 3)],
                    parking_type=parking_type,
                    time_limit_seconds=2,
                )
                self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
                self.assertIsNotNone(result.parking)
                self.assertEqual(result.parking_type, parking_type)
                metrics = calculate_metrics(
                    10,
                    10,
                    result.placements,
                    parking=result.parking,
                    number_of_floors=1,
                )
                self.assertEqual(metrics.parking_area, expected_area)
                self.assertEqual(metrics.overlap_count, 0)
                self.assertEqual(metrics.boundary_violation_count, 0)
                self.assertEqual(
                    metrics.total_allocated_site_area,
                    metrics.building_footprint_area + expected_area,
                )

    def test_parking_dimensions_are_configurable(self):
        result = solve_layout(
            10,
            10,
            [Room("Room", 2, 2)],
            parking_type="1 car",
            parking_width=3.25,
            parking_length=4.5,
            time_limit_seconds=2,
        )

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertIsNotNone(result.parking)
        self.assertEqual((result.parking.width, result.parking.length), (3.25, 4.5))

    def test_ground_floor_entry_anchor_touches_selected_road_side(self):
        rooms = [
            Room("Entry Foyer", 2.0, 2.0, floor=1),
            Room("Living Room", 4.0, 4.0, floor=1),
            Room("Bedroom 1", 3.0, 3.0, floor=2),
        ]
        result = solve_layout(20, 20, rooms, number_of_floors=2, road_access="South", time_limit_seconds=2)
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        foyer = next(room for room in result.placements if room.name == "Entry Foyer")
        self.assertAlmostEqual(foyer.y, 0.0)

    def test_staircase_is_kept_near_circulation_anchor(self):
        rooms = [
            Room("Entry Foyer", 2.0, 2.0, floor=1),
            Room("Living Room", 4.0, 4.0, floor=1),
            Room("Family Lounge", 4.0, 4.0, floor=2),
        ]
        result = solve_layout(20, 20, rooms, number_of_floors=2, road_access="South", time_limit_seconds=2)
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        foyer = next(room for room in result.placements if room.name == "Entry Foyer")
        staircase = result.staircases[0]
        foyer_center = (foyer.x + foyer.width / 2, foyer.y + foyer.length / 2)
        stair_center = (staircase.x + staircase.width / 2, staircase.y + staircase.length / 2)
        manhattan_distance = abs(foyer_center[0] - stair_center[0]) + abs(foyer_center[1] - stair_center[1])
        self.assertLessEqual(manhattan_distance, 6.0)

    def test_parking_prefers_selected_road_side(self):
        cases = (
            ("South", lambda p: p.y),
            ("North", lambda p: 10 - p.y - p.length),
            ("West", lambda p: p.x),
            ("East", lambda p: 10 - p.x - p.width),
        )
        for side, distance_from_side in cases:
            with self.subTest(side=side):
                result = solve_layout(
                    10,
                    10,
                    [Room("Room", 2, 2)],
                    parking_type="1 car",
                    parking_width=2,
                    parking_length=2,
                    road_access=side,
                    time_limit_seconds=2,
                )
                self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
                self.assertIsNotNone(result.parking)
                self.assertLessEqual(distance_from_side(result.parking), 0.01)
                self.assertEqual(result.road_access, side)

    def test_attached_works_on_same_floor_in_multistory_layout(self):
        relationships = [RoomRelationship("A", "B", "ATTACHED")]
        result = solve_layout(
            8,
            8,
            [
                Room("A", 2, 2, floor=1),
                Room("B", 2, 2, floor=1),
                Room("Upper", 2, 2, floor=2),
            ],
            relationships=relationships,
            number_of_floors=2,
            time_limit_seconds=2,
        )

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        metrics = calculate_metrics(
            8,
            8,
            result.placements,
            relationships,
            number_of_floors=2,
            staircases=result.staircases,
        )
        self.assertEqual((metrics.attached_satisfied, metrics.attached_total), (1, 1))

    def test_cross_floor_attached_relationship_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "same floor"):
            solve_layout(
                8,
                8,
                [Room("A", 2, 2, floor=1), Room("B", 2, 2, floor=2)],
                relationships=[RoomRelationship("A", "B", "ATTACHED")],
                number_of_floors=2,
            )

    def test_stacked_metric_uses_actual_room_center_distance(self):
        relationships = [RoomRelationship("A", "B", "STACKED")]
        metrics = calculate_metrics(
            10,
            10,
            [
                Placement("A", 0, 0, 2, 2, floor=1),
                Placement("B", 3, 0, 2, 2, floor=2),
            ],
            relationships,
            number_of_floors=2,
        )

        self.assertEqual((metrics.stacked_satisfied, metrics.stacked_total), (0, 1))
        self.assertEqual(metrics.stacked_center_distance_total, 3)
        self.assertEqual(metrics.relationship_satisfaction_percent, 0)
        self.assertEqual(metrics.soft_penalty_distance_total, 3)

    def test_stacked_is_a_soft_objective_that_aligns_when_possible(self):
        relationships = [RoomRelationship("Lower", "Upper", "STACKED")]
        result = solve_layout(
            8,
            8,
            [
                Room("Lower", 2, 2, floor=1),
                Room("Upper", 2, 2, floor=2),
            ],
            relationships=relationships,
            number_of_floors=2,
            time_limit_seconds=2,
        )

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        metrics = calculate_metrics(
            8,
            8,
            result.placements,
            relationships,
            number_of_floors=2,
            staircases=result.staircases,
        )
        self.assertEqual((metrics.stacked_satisfied, metrics.stacked_total), (1, 1))
        self.assertEqual(metrics.stacked_center_distance_total, 0)

    def test_cross_floor_near_relationship_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "same floor"):
            solve_layout(
                8,
                8,
                [Room("A", 2, 2, floor=1), Room("B", 2, 2, floor=2)],
                relationships=[RoomRelationship("A", "B", "NEAR")],
                number_of_floors=2,
            )

    def test_floor_plan_labels_floors_and_shows_parking_only_on_floor_one(self):
        room = Placement("Room", 0, 0, 2, 2, floor=1)
        parking = Placement("Parking (1 car)", 5, 0, 2.5, 5, floor=0, floor_end=0)
        staircase = Placement("Staircase F1-F2", 3, 0, 2, 4, floor=1, floor_end=2)
        first_floor = create_floor_plan(
            10,
            10,
            [room],
            floor_number=1,
            parking=parking,
            staircases=[staircase],
        )
        second_floor = create_floor_plan(
            10,
            10,
            [Placement("Upper room", 0, 0, 2, 2, floor=2)],
            floor_number=2,
            parking=parking,
            staircases=[staircase],
        )
        try:
            self.assertIn("GROUND FLOOR", first_floor.axes[0].get_title(loc="left"))
            self.assertIn("FIRST FLOOR", second_floor.axes[0].get_title(loc="left"))
            self.assertEqual(len(first_floor.axes[0].patches), 5)
            self.assertEqual(len(second_floor.axes[0].patches), 4)
        finally:
            plt.close(first_floor)
            plt.close(second_floor)

    def test_floor_plan_marks_site_gates_and_selected_main_entrance(self):
        figure = create_floor_plan(
            20,
            12,
            [Placement("Entry Foyer", 2, 2, 6, 4, floor=1)],
            floor_number=1,
            road_access="South",
            entrance_side="North",
            entrance_room_name="Entry Foyer",
            unit_label="ft",
        )
        try:
            labels = [text.get_text() for text in figure.axes[0].texts]
            self.assertTrue(any("Vehicle gate" in label for label in labels))
            self.assertTrue(any("Pedestrian gate" in label for label in labels))
            self.assertTrue(any("Main entrance" in label for label in labels))
            self.assertEqual(len(figure.axes[0].collections), 2)
        finally:
            plt.close(figure)


if __name__ == "__main__":
    unittest.main()
