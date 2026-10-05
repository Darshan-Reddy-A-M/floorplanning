import math
import unittest

from ortools.sat.python import cp_model
from testfit.defaults import DEFAULT_RELATIONSHIPS, DEFAULT_ROOMS
from testfit.optimizer import (
    MIN_ATTACHED_EDGE,
    MIN_ATTACHED_EDGE_UNITS,
    Placement,
    Room,
    RoomRelationship,
    _add_hard_edge_touch_constraint,
    calculate_metrics,
    solve_layout,
)


def positive_shared_edge_length(first, second):
    """Return the positive coincident-edge span, or zero for a point contact."""
    vertical_span = 0.0
    if (
        math.isclose(first.x + first.width, second.x, rel_tol=0, abs_tol=1e-9)
        or math.isclose(second.x + second.width, first.x, rel_tol=0, abs_tol=1e-9)
    ):
        vertical_span = max(
            0.0,
            min(first.y + first.length, second.y + second.length)
            - max(first.y, second.y),
        )

    horizontal_span = 0.0
    if (
        math.isclose(first.y + first.length, second.y, rel_tol=0, abs_tol=1e-9)
        or math.isclose(second.y + second.length, first.y, rel_tol=0, abs_tol=1e-9)
    ):
        horizontal_span = max(
            0.0,
            min(first.x + first.width, second.x + second.width)
            - max(first.x, second.x),
        )
    return max(vertical_span, horizontal_span)


class SolveLayoutTests(unittest.TestCase):
    def fixed_pair_attachment_status(
        self,
        first_position,
        second_position,
        minimum_shared_edge_units=1,
    ):
        model = cp_model.CpModel()
        x_positions = [model.new_int_var(0, 500, f"x_{i}") for i in range(2)]
        y_positions = [model.new_int_var(0, 500, f"y_{i}") for i in range(2)]
        model.add(x_positions[0] == first_position[0])
        model.add(y_positions[0] == first_position[1])
        model.add(x_positions[1] == second_position[0])
        model.add(y_positions[1] == second_position[1])
        _add_hard_edge_touch_constraint(
            model,
            relationship_index=0,
            first_index=0,
            second_index=1,
            first_width=200,
            first_length=200,
            second_width=200,
            second_length=200,
            x_positions=x_positions,
            y_positions=y_positions,
            minimum_shared_edge_units=minimum_shared_edge_units,
        )
        solver = cp_model.CpSolver()
        return solver.status_name(solver.solve(model))

    def test_default_example_produces_valid_layout(self):
        result = solve_layout(
            20, 15, DEFAULT_ROOMS, relationships=DEFAULT_RELATIONSHIPS
        )

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(len(result.placements), len(DEFAULT_ROOMS))
        metrics = calculate_metrics(
            20, 15, result.placements, DEFAULT_RELATIONSHIPS
        )
        self.assertEqual(metrics.site_area, 300)
        self.assertEqual(metrics.total_room_area, 81)
        self.assertEqual(metrics.unused_area, 219)
        self.assertEqual(metrics.overlap_count, 0)
        self.assertEqual(metrics.boundary_violation_count, 0)
        self.assertEqual((metrics.attached_satisfied, metrics.attached_total), (2, 2))
        self.assertEqual((metrics.adjacent_satisfied, metrics.adjacent_total), (1, 1))
        self.assertEqual((metrics.near_satisfied, metrics.near_total), (1, 1))
        self.assertEqual((metrics.preferred_satisfied, metrics.preferred_total), (1, 1))
        self.assertGreaterEqual(metrics.soft_penalty_distance_total, 0)
        self.assertLess(metrics.soft_penalty_distance_total, 1)
        self.assertEqual(metrics.relationship_satisfaction_percent, 100)
        placements = {placement.name: placement for placement in result.placements}
        for bedroom, bathroom in (
            ("Bedroom 1", "Bathroom 1"),
            ("Bedroom 2", "Bathroom 2"),
        ):
            with self.subTest(pair=(bedroom, bathroom)):
                self.assertGreater(
                    positive_shared_edge_length(
                        placements[bedroom], placements[bathroom]
                    ),
                    MIN_ATTACHED_EDGE - 1e-9,
                )

    def test_relationship_metrics_check_actual_edge_geometry(self):
        placements = [
            Placement("A", 0, 0, 2, 2),
            Placement("Touching", 2, 0.5, 1, 1),
            Placement("Gap", 3.1, 0, 1, 1),
            Placement("Corner", 2, 2, 1, 1),
        ]
        relationships = [
            RoomRelationship("A", "Touching", "ATTACHED"),
            RoomRelationship("A", "Gap", "ADJACENT"),
            RoomRelationship("A", "Corner", "ADJACENT"),
        ]

        metrics = calculate_metrics(5, 5, placements, relationships)

        self.assertEqual(metrics.attached_satisfied, 1)
        self.assertEqual(metrics.attached_total, 1)
        self.assertEqual(metrics.adjacent_satisfied, 0)
        self.assertEqual(metrics.adjacent_total, 2)
        self.assertAlmostEqual(metrics.relationship_satisfaction_percent, 100 / 3)
        self.assertEqual(metrics.overlap_count, 0)
        self.assertEqual(metrics.boundary_violation_count, 0)

    def test_attached_audit_accepts_positive_vertical_shared_edge(self):
        metrics = calculate_metrics(
            5,
            5,
            [Placement("A", 0, 0, 2, 2), Placement("B", 2, 0.5, 1, 1)],
            [RoomRelationship("A", "B", "ATTACHED")],
        )
        self.assertEqual((metrics.attached_satisfied, metrics.attached_total), (1, 1))
        self.assertEqual(metrics.overlap_count, 0)

    def test_attached_audit_accepts_positive_horizontal_shared_edge(self):
        metrics = calculate_metrics(
            5,
            5,
            [Placement("A", 0, 0, 2, 2), Placement("B", 0.5, 2, 1, 1)],
            [RoomRelationship("A", "B", "ATTACHED")],
        )
        self.assertEqual((metrics.attached_satisfied, metrics.attached_total), (1, 1))
        self.assertEqual(metrics.overlap_count, 0)

    def test_attached_audit_rejects_corner_only_contact(self):
        metrics = calculate_metrics(
            5,
            5,
            [Placement("A", 0, 0, 2, 2), Placement("B", 2, 2, 1, 1)],
            [RoomRelationship("A", "B", "ATTACHED")],
        )
        self.assertEqual((metrics.attached_satisfied, metrics.attached_total), (0, 1))
        self.assertEqual(metrics.overlap_count, 0)

    def test_attached_audit_rejects_a_gap(self):
        metrics = calculate_metrics(
            5,
            5,
            [Placement("A", 0, 0, 2, 2), Placement("B", 2.1, 0, 1, 1)],
            [RoomRelationship("A", "B", "ATTACHED")],
        )
        self.assertEqual((metrics.attached_satisfied, metrics.attached_total), (0, 1))
        self.assertEqual(metrics.overlap_count, 0)

    def test_attached_audit_rejects_overlapping_rooms(self):
        metrics = calculate_metrics(
            5,
            5,
            [Placement("A", 0, 0, 2, 2), Placement("B", 1, 1, 1, 1)],
            [RoomRelationship("A", "B", "ATTACHED")],
        )
        self.assertEqual((metrics.attached_satisfied, metrics.attached_total), (0, 1))
        self.assertEqual(metrics.overlap_count, 1)

    def test_attached_audit_uses_configurable_minimum_shared_edge(self):
        cases = (
            (0.01, False),
            (0.49, False),
            (0.50, True),
            (1.0, True),
            (2.0, True),
        )
        self.assertEqual(MIN_ATTACHED_EDGE, 0.5)
        for shared_length, expected in cases:
            with self.subTest(shared_length=shared_length):
                metrics = calculate_metrics(
                    5,
                    5,
                    [
                        Placement("A", 0, 0, 2, 2),
                        Placement("B", 2, 2 - shared_length, 2, 2),
                    ],
                    [RoomRelationship("A", "B", "ATTACHED")],
                )
                self.assertEqual(
                    (metrics.attached_satisfied, metrics.attached_total),
                    (int(expected), 1),
                )
                self.assertEqual(metrics.overlap_count, 0)

    def test_adjacent_keeps_any_positive_shared_edge_requirement(self):
        metrics = calculate_metrics(
            5,
            5,
            [
                Placement("A", 0, 0, 2, 2),
                Placement("B", 2, 1.99, 1, 1),
            ],
            [RoomRelationship("A", "B", "ADJACENT")],
        )
        self.assertEqual((metrics.adjacent_satisfied, metrics.adjacent_total), (1, 1))

    def test_cp_sat_attachment_requires_positive_non_overlapping_edge(self):
        self.assertEqual(
            self.fixed_pair_attachment_status((0, 0), (200, 100)), "OPTIMAL"
        )
        self.assertEqual(
            self.fixed_pair_attachment_status((0, 0), (100, 200)), "OPTIMAL"
        )
        self.assertEqual(
            self.fixed_pair_attachment_status((0, 0), (200, 200)), "INFEASIBLE"
        )
        self.assertEqual(
            self.fixed_pair_attachment_status((0, 0), (201, 0)), "INFEASIBLE"
        )
        self.assertEqual(
            self.fixed_pair_attachment_status((0, 0), (100, 100)), "INFEASIBLE"
        )

    def test_cp_sat_attachment_uses_configurable_minimum_shared_edge(self):
        cases = (
            (0.01, False),
            (0.49, False),
            (0.50, True),
            (1.0, True),
            (2.0, True),
        )
        for shared_length, expected in cases:
            with self.subTest(shared_length=shared_length):
                shared_edge_units = round(shared_length * 100)
                status = self.fixed_pair_attachment_status(
                    (0, 0),
                    (200, 200 - shared_edge_units),
                    minimum_shared_edge_units=MIN_ATTACHED_EDGE_UNITS,
                )
                self.assertEqual(status == "OPTIMAL", expected)

    def test_room_dimensions_in_solver_output_match_centimeter_grid(self):
        result = solve_layout(
            5,
            5,
            [Room("A", 1.004, 1), Room("B", 1, 1)],
            relationships=[RoomRelationship("A", "B", "ATTACHED")],
        )
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        room_a = next(
            placement for placement in result.placements if placement.name == "A"
        )
        self.assertEqual(room_a.width, 1.0)
        metrics = calculate_metrics(
            5,
            5,
            result.placements,
            [RoomRelationship("A", "B", "ATTACHED")],
        )
        self.assertEqual((metrics.attached_satisfied, metrics.attached_total), (1, 1))
        self.assertEqual(metrics.overlap_count, 0)

    def test_soft_relationship_metrics_use_actual_rectilinear_gaps(self):
        placements = [
            Placement("A", 0, 0, 2, 2),
            Placement("Close", 2.5, 0, 2, 2),
            Placement("Far", 6.5, 0, 2, 2),
        ]
        relationships = [
            RoomRelationship("A", "Close", "NEAR"),
            RoomRelationship("A", "Far", "NEAR"),
            RoomRelationship("A", "Close", "PREFERRED"),
            RoomRelationship("A", "Far", "PREFERRED"),
        ]

        metrics = calculate_metrics(10, 3, placements, relationships)

        self.assertEqual((metrics.near_satisfied, metrics.near_total), (1, 2))
        self.assertEqual((metrics.preferred_satisfied, metrics.preferred_total), (1, 2))
        self.assertAlmostEqual(metrics.near_distance_total, 5.0)
        self.assertAlmostEqual(metrics.preferred_penalty_total, 3.5)
        self.assertAlmostEqual(metrics.soft_penalty_distance_total, 8.5)
        self.assertAlmostEqual(metrics.relationship_satisfaction_percent, 50.0)
        self.assertEqual(metrics.overlap_count, 0)
        self.assertEqual(metrics.boundary_violation_count, 0)

    def test_compactness_metrics_use_actual_occupied_bounding_box(self):
        placements = [
            Placement("A", 3, 4, 2, 2),
            Placement("B", 7, 6, 1, 3),
        ]

        metrics = calculate_metrics(12, 10, placements)

        self.assertEqual(metrics.site_area, 120)
        self.assertEqual(metrics.total_room_area, 7)
        self.assertEqual(metrics.unused_area, 113)
        self.assertAlmostEqual(metrics.utilization_percent, 7 / 120 * 100)
        self.assertAlmostEqual(metrics.occupied_width, 5)
        self.assertAlmostEqual(metrics.occupied_length, 5)
        self.assertAlmostEqual(metrics.occupied_bbox_area, 25)
        self.assertAlmostEqual(metrics.layout_compactness_percent, 28)

    def test_distant_soft_relationships_do_not_make_layout_infeasible(self):
        rooms = [
            Room("A", 2, 2),
            Room("Middle", 2, 2),
            Room("B", 2, 2),
        ]
        relationships = [
            RoomRelationship("A", "Middle", "ADJACENT"),
            RoomRelationship("Middle", "B", "ADJACENT"),
            RoomRelationship("A", "B", "NEAR"),
            RoomRelationship("A", "B", "PREFERRED"),
        ]

        result = solve_layout(6, 2, rooms, relationships=relationships)

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        metrics = calculate_metrics(6, 2, result.placements, relationships)
        self.assertEqual(metrics.overlap_count, 0)
        self.assertEqual(metrics.boundary_violation_count, 0)
        self.assertEqual((metrics.adjacent_satisfied, metrics.adjacent_total), (2, 2))
        self.assertEqual((metrics.near_satisfied, metrics.near_total), (0, 1))
        self.assertEqual((metrics.preferred_satisfied, metrics.preferred_total), (0, 1))
        self.assertAlmostEqual(metrics.near_distance_total, 2.0)
        self.assertAlmostEqual(metrics.preferred_penalty_total, 1.0)

    def test_infeasible_room_larger_than_site(self):
        result = solve_layout(5, 5, [Room("Too large", 6, 2)])
        self.assertEqual(result.status, "INFEASIBLE")
        self.assertEqual(result.placements, [])

    def test_invalid_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            solve_layout(0, 10, [Room("Room", 2, 2)])

    def test_metrics_count_overlaps_and_boundary_violations(self):
        metrics = calculate_metrics(
            5,
            5,
            [
                Placement("A", -1, 0, 3, 3),
                Placement("B", 1, 1, 3, 3),
            ],
        )
        self.assertEqual(metrics.overlap_count, 1)
        self.assertEqual(metrics.boundary_violation_count, 1)

    def test_relationship_must_reference_existing_rooms(self):
        with self.assertRaisesRegex(ValueError, "not in the room list"):
            solve_layout(
                10,
                10,
                [Room("A", 2, 2)],
                relationships=[RoomRelationship("A", "Missing", "ATTACHED")],
            )


if __name__ == "__main__":
    unittest.main()