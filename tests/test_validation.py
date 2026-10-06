"""Tests for the OR-Tools-free validator, using hand-built layouts.

Each hard check is proven to catch a known-bad layout, and each quality metric
is checked against a case whose exact answer is computed by hand.
"""

import json
import pathlib
import subprocess
import sys
import unittest

from testfit.validation import (
    LayoutSnapshot,
    RectSpec,
    classify_room,
    compute_quality,
    evaluate,
    format_text,
    legacy_gate_points,
    run_hard_checks,
    to_json,
)
from testfit.validation.geometry import (
    boxes_overlap,
    shared_edge_cm,
    to_box,
    void_analysis,
)
from tests.fixtures.sample_configs import SAMPLE_CONFIGS

ROOT = pathlib.Path(__file__).resolve().parents[1]


def R(name, x, y, w, l, floor=1, floor_end=None):
    return RectSpec(name, x, y, w, l, floor, floor_end)


def snap(rooms, **kw):
    kw.setdefault("site_width", 20.0)
    kw.setdefault("site_length", 20.0)
    kw.setdefault("number_of_floors", 1)
    kw.setdefault("status", "OPTIMAL")
    return LayoutSnapshot(rooms=rooms, **kw)


def check(snapshot, name):
    return next(c for c in run_hard_checks(snapshot) if c.name == name)


class GeometryTests(unittest.TestCase):
    def test_touching_rooms_do_not_overlap(self):
        self.assertFalse(boxes_overlap(to_box(R("A", 0, 0, 3, 3)), to_box(R("B", 3, 0, 3, 3))))

    def test_shared_edge_lengths(self):
        a = to_box(R("A", 0, 0, 3, 3))
        self.assertEqual(shared_edge_cm(a, to_box(R("B", 3, 1, 3, 3))), 200)
        self.assertEqual(shared_edge_cm(a, to_box(R("C", 3, 3, 3, 3))), 0)  # corner only
        self.assertEqual(shared_edge_cm(a, to_box(R("D", 3.5, 0, 3, 3))), 0)  # gap
        self.assertEqual(shared_edge_cm(a, to_box(R("E", 1, 1, 3, 3))), 0)  # overlap

    def test_void_two_rooms_with_a_gap(self):
        info = void_analysis([to_box(R("A", 0, 0, 4, 4)), to_box(R("B", 6, 0, 4, 4))])
        self.assertEqual(info["void_area"], 8 * 10_000)
        self.assertEqual(info["largest_empty_rect_area"], 8 * 10_000)
        self.assertEqual(info["void_components"], 1)

    def test_void_l_shape(self):
        info = void_analysis(
            [to_box(R("A", 0, 0, 4, 4)), to_box(R("B", 4, 0, 4, 4)), to_box(R("C", 0, 4, 4, 4))]
        )
        self.assertEqual(info["void_area"], 16 * 10_000)
        self.assertEqual(info["largest_empty_rect_dims"], (400, 400))

    def test_fully_tiled_has_no_void(self):
        info = void_analysis([to_box(R("A", 0, 0, 3, 3)), to_box(R("B", 3, 0, 3, 3))])
        self.assertEqual(info["void_area"], 0)


class HardCheckTests(unittest.TestCase):
    def test_clean_layout_passes_everything(self):
        s = snap([R("A", 0, 0, 3, 3), R("B", 3, 0, 3, 3)],
                 relationships=[("A", "B", "ATTACHED")])
        self.assertTrue(all(c.passed for c in run_hard_checks(s)))

    def test_overlap_detected_same_floor_only(self):
        same = snap([R("A", 0, 0, 3, 3), R("B", 2, 2, 3, 3)])
        self.assertFalse(check(same, "no_overlap_rooms_and_stairs").passed)
        different = snap([R("A", 0, 0, 3, 3, 1), R("B", 2, 2, 3, 3, 2)], number_of_floors=2)
        self.assertTrue(check(different, "no_overlap_rooms_and_stairs").passed)

    def test_boundary_containment_uses_buildable_bounds(self):
        s = snap([R("A", 1, 5, 3, 3)], buildable_bounds=(2, 2, 18, 18))
        self.assertFalse(check(s, "boundary_containment_buildable").passed)
        ok = snap([R("A", 2, 2, 3, 3)], buildable_bounds=(2, 2, 18, 18))
        self.assertTrue(check(ok, "boundary_containment_buildable").passed)

    def test_attached_requires_half_a_meter(self):
        for y, expected in ((2.6, False), (2.5, True), (3.0, False)):
            with self.subTest(offset=y):
                s = snap([R("A", 0, 0, 3, 3), R("B", 3, y, 3, 3)],
                         relationships=[("A", "B", "ATTACHED")])
                self.assertEqual(check(s, "attached_min_0.5m").passed, expected)

    def test_attached_rejects_a_gap_and_overlap(self):
        for bx in (3.5, 2.0):
            s = snap([R("A", 0, 0, 3, 3), R("B", bx, 0, 3, 3)],
                     relationships=[("A", "B", "ATTACHED")])
            self.assertFalse(check(s, "attached_min_0.5m").passed)

    def test_adjacent_accepts_one_centimeter(self):
        s = snap([R("A", 0, 0, 3, 3), R("B", 3, 2.99, 3, 3)],
                 relationships=[("A", "B", "ADJACENT")])
        self.assertTrue(check(s, "adjacent_positive_edge").passed)

    def test_cross_floor_hard_relationship_is_a_rule_violation(self):
        s = snap([R("A", 0, 0, 3, 3, 1), R("B", 3, 0, 3, 3, 2)], number_of_floors=2,
                 relationships=[("A", "B", "ATTACHED")])
        self.assertFalse(check(s, "relationship_floor_rules").passed)

    def test_stacked_needs_adjacent_floors(self):
        s = snap([R("A", 0, 0, 3, 3, 1), R("B", 0, 0, 3, 3, 3)], number_of_floors=3,
                 relationships=[("A", "B", "STACKED")])
        self.assertFalse(check(s, "relationship_floor_rules").passed)

    def test_parking_must_avoid_rooms_on_every_floor(self):
        s = snap([R("Up", 0, 0, 4, 4, 2)], number_of_floors=2, parking=R("Parking", 1, 1, 2, 2, 0, 0))
        self.assertFalse(check(s, "parking_no_overlap").passed)

    def test_parking_must_stay_inside_site(self):
        s = snap([R("A", 0, 0, 3, 3)], parking=R("Parking", 19, 5, 2, 2, 0, 0))
        self.assertFalse(check(s, "parking_inside_site").passed)

    def test_parking_dimensions_match_request(self):
        s = snap([R("A", 0, 0, 3, 3)], parking=R("Parking", 10, 0, 2.5, 5, 0, 0),
                 expected_parking=(2.5, 5.0))
        self.assertTrue(check(s, "parking_dimensions").passed)
        s.expected_parking = (3.0, 5.0)
        self.assertFalse(check(s, "parking_dimensions").passed)

    def test_staircase_must_connect_every_floor_pair(self):
        rooms = [R(f"R{f}", 10, 10, 2, 2, f) for f in (1, 2, 3)]
        short = snap(rooms, number_of_floors=3, staircases=[R("Stair", 0, 0, 2, 4, 1, 2)])
        self.assertFalse(check(short, "staircase_valid_continuous").passed)
        full = snap(rooms, number_of_floors=3, staircases=[R("Stair", 0, 0, 2, 4, 1, 3)])
        self.assertTrue(check(full, "staircase_valid_continuous").passed)
        missing = snap(rooms, number_of_floors=3)
        self.assertFalse(check(missing, "staircase_valid_continuous").passed)

    def test_single_floor_building_has_no_stair(self):
        s = snap([R("A", 0, 0, 3, 3)], staircases=[R("Stair", 5, 5, 2, 4, 1, 1)])
        self.assertFalse(check(s, "staircase_valid_continuous").passed)

    def test_stair_overlap_is_detected(self):
        s = snap([R("A", 0, 0, 3, 3, 1), R("B", 0, 0, 3, 3, 2)], number_of_floors=2,
                 staircases=[R("Stair", 1, 1, 2, 4, 1, 2)])
        self.assertFalse(check(s, "no_overlap_rooms_and_stairs").passed)

    def test_fixed_room_sizes_must_match_request(self):
        s = snap([R("A", 0, 0, 3.5, 3)], expected_rooms={"A": (3.0, 3.0, 1)})
        self.assertFalse(check(s, "rooms_match_request_fixed_size").passed)

    def test_floor_out_of_range_and_duplicate_names(self):
        s = snap([R("A", 0, 0, 3, 3, 4)], number_of_floors=2)
        self.assertFalse(check(s, "floor_range_1_to_5").passed)
        dup = snap([R("A", 0, 0, 3, 3), R("A", 5, 0, 3, 3)])
        self.assertFalse(check(dup, "finite_positive_unique").passed)

    def test_more_than_five_floors_rejected(self):
        s = snap([R("A", 0, 0, 3, 3)], number_of_floors=6)
        self.assertFalse(check(s, "floor_range_1_to_5").passed)


class QualityTests(unittest.TestCase):
    def floor(self, snapshot, floor=1):
        return compute_quality(snapshot)["floors"][floor - 1]

    def test_void_and_isolation_metrics(self):
        s = snap([R("A", 0, 0, 3, 3), R("B", 3, 0, 3, 3), R("C", 10, 10, 3, 3)])
        f = self.floor(s)
        self.assertEqual(f["isolated_elements"], ["C"])
        self.assertEqual(f["clusters_touching"], 2)
        self.assertGreater(f["void_pct"], 50)

    def test_tight_pair_has_no_void(self):
        f = self.floor(snap([R("A", 0, 0, 3, 3), R("B", 3, 0, 3, 3)]))
        self.assertAlmostEqual(f["void_pct"], 0.0)
        self.assertEqual(f["clusters_connectable"], 1)

    def test_short_shared_edge_does_not_make_a_door_connection(self):
        f = self.floor(snap([R("A", 0, 0, 3, 3), R("B", 3, 2.5, 3, 3)]))
        self.assertEqual(f["clusters_touching"], 1)
        self.assertEqual(f["clusters_connectable"], 2)

    def test_enclosed_habitable_room_is_flagged(self):
        rooms = [R("Living Room", 3, 3, 3, 3)]
        k = 0
        for gx in range(3):
            for gy in range(3):
                if (gx, gy) != (1, 1):
                    rooms.append(R(f"Store {k}", gx * 3, gy * 3, 3, 3))
                    k += 1
        f = self.floor(snap(rooms))
        self.assertEqual(f["fully_enclosed_habitable"], ["Living Room"])

    def test_upper_floor_overhang(self):
        s = snap([R("G", 0, 0, 4, 4, 1), R("U", 2, 0, 4, 4, 2)], number_of_floors=2)
        self.assertAlmostEqual(compute_quality(s)["vertical"]["upper_floor_overhang_m2"][2], 8.0)

    def stair_connection(self, neighbor_name):
        s = snap(
            [R(neighbor_name, 0, 0, 3, 3, 1), R("Up", 0, 0, 3, 3, 2)],
            number_of_floors=2,
            staircases=[R("Staircase", 3, 0, 2, 3, 1, 2)],
        )
        return compute_quality(s)["stairs"][0]["connection"]

    def test_stair_connection_classes(self):
        self.assertEqual(self.stair_connection("Entry Foyer"), "circulation")
        self.assertEqual(self.stair_connection("Living Room"), "common_room")
        self.assertEqual(self.stair_connection("Bedroom 1"), "private_or_service_only")
        s = snap([R("Living Room", 10, 10, 3, 3), R("Up", 0, 0, 3, 3, 2)], number_of_floors=2,
                 staircases=[R("Staircase", 3, 0, 2, 3, 1, 2)])
        self.assertEqual(compute_quality(s)["stairs"][0]["connection"], "none")

    def test_reachability_through_rooms_and_stairs(self):
        s = snap(
            [R("Foyer", 0, 0, 3, 3, 1), R("Far", 15, 15, 3, 3, 1),
             R("Bed", 5, 0, 3, 3, 2), R("Lost", 12, 12, 3, 3, 2)],
            number_of_floors=2, entrance_room="Foyer",
            staircases=[R("Stair", 3, 0, 2, 3, 1, 2)],
        )
        reach = compute_quality(s)["reachability"]
        self.assertTrue(reach["entrance_found"])
        self.assertEqual(reach["unreachable"], ["Far (floor 1)", "Lost (floor 2)"])

    def test_reachability_without_entrance_is_reported(self):
        reach = compute_quality(snap([R("A", 0, 0, 3, 3)]))["reachability"]
        self.assertFalse(reach["entrance_found"])

    def test_soft_relationship_counts(self):
        s = snap([R("A", 0, 0, 3, 3), R("B", 3.5, 0, 3, 3), R("C", 10, 0, 3, 3)],
                 relationships=[("A", "B", "NEAR"), ("A", "C", "NEAR")])
        rel = compute_quality(s)["relationships"]["NEAR"]
        self.assertEqual((rel["satisfied"], rel["total"]), (1, 2))

    def test_classify_room(self):
        cases = {"Entry Foyer": "circulation", "Bedroom 2": "private", "Living Room": "common",
                 "Kitchen": "service", "Floor 2 · Unit 1 Bathroom": "private",
                 "Family Lounge": "common", "Garage Workshop": "other"}
        for name, expected in cases.items():
            self.assertEqual(classify_room(name), expected, name)


class GateTests(unittest.TestCase):
    def points(self, road, entrance_side, parking=None, room=None):
        return legacy_gate_points(
            site_width=20, site_length=30, road_access=road, entrance_side=entrance_side,
            parking=parking, entrance_room=room,
        )

    def test_legacy_projection_matches_renderer_rules(self):
        room = R("Foyer", 2, 3, 4, 4)
        east = self.points("North", "East", room=room)
        self.assertEqual(east["pedestrian_gate"], (20.0, 5.0))
        self.assertEqual(east["entrance_door"], (6.0, 5.0))
        north = self.points("North", "North", room=room)
        self.assertEqual(north["pedestrian_gate"], (4.0, 30.0))
        self.assertEqual(north["entrance_door"], (4.0, 7.0))

    def site_snapshot(self, **gates):
        return snap([R("Foyer", 2, 3, 4, 4)], site_width=20, site_length=30, road_access="North",
                    entrance_side="North", entrance_room="Foyer",
                    parking=R("Parking", 10, 25, 3, 5, 0, 0), gate_source="legacy_projection", **gates)

    def test_gate_distances_use_actual_coordinates(self):
        s = self.site_snapshot()
        g = self.points("North", "North", parking=s.parking, room=s.rooms[0])
        s.vehicle_gate, s.pedestrian_gate, s.entrance_door = (
            g["vehicle_gate"], g["pedestrian_gate"], g["entrance_door"])
        site = compute_quality(s)["site"]
        self.assertAlmostEqual(site["vehicle_gate_to_parking_m"], 0.0)
        self.assertAlmostEqual(site["pedestrian_gate_to_door_m"], 23.0)
        self.assertAlmostEqual(site["entrance_room_gap_to_buildable_edge_m"], 23.0)
        self.assertAlmostEqual(site["parking_gap_to_road_edge_m"], 0.0)

    def test_scorecard_flags_far_entrance(self):
        s = self.site_snapshot()
        g = self.points("North", "North", parking=s.parking, room=s.rooms[0])
        s.vehicle_gate, s.pedestrian_gate, s.entrance_door = (
            g["vehicle_gate"], g["pedestrian_gate"], g["entrance_door"])
        card = {e["metric"]: e for e in evaluate(s)["scorecard"]}
        self.assertEqual(card["pedestrian_gate_to_door_m"]["status"], "fail")
        self.assertEqual(card["vehicle_gate_to_parking_m"]["status"], "pass")

    def test_far_parking_is_flagged(self):
        s = snap([R("Foyer", 0, 0, 3, 3)], road_access="South", entrance_room="Foyer",
                 parking=R("Parking", 10, 12, 3, 5, 0, 0))
        s.vehicle_gate = (11.5, 0.0)
        card = {e["metric"]: e for e in evaluate(s)["scorecard"]}
        self.assertEqual(card["vehicle_gate_to_parking_m"]["status"], "fail")


class ReportTests(unittest.TestCase):
    def clean(self):
        s = snap([R("Foyer", 0, 0, 3, 3), R("Living", 3, 0, 3, 3), R("Bed", 6, 0, 3, 3)],
                 road_access="South", entrance_side="South", entrance_room="Foyer")
        g = legacy_gate_points(site_width=20, site_length=20, road_access="South",
                               entrance_side="South", parking=None, entrance_room=s.rooms[0])
        s.vehicle_gate, s.pedestrian_gate, s.entrance_door = (
            g["vehicle_gate"], g["pedestrian_gate"], g["entrance_door"])
        return s

    def test_clean_layout_is_ok(self):
        report = evaluate(self.clean(), "clean")
        self.assertEqual(report["verdict"], "OK", format_text(report))
        self.assertEqual(report["summary"]["fail"], 0)

    def test_hard_failure_makes_layout_invalid(self):
        s = self.clean()
        s.rooms.append(R("Bad", 1, 1, 3, 3))
        report = evaluate(s)
        self.assertEqual(report["verdict"], "INVALID")
        self.assertFalse(report["hard_pass"])
        self.assertIn("HARD FAIL", format_text(report))

    def test_infeasible_status_has_no_layout_verdict(self):
        report = evaluate(snap([], status="INFEASIBLE"))
        self.assertEqual(report["verdict"], "NO_LAYOUT")

    def test_poor_quality_layout_is_valid_but_not_ok(self):
        s = self.clean()
        s.rooms.append(R("Floating", 14, 14, 3, 3))
        report = evaluate(s)
        self.assertTrue(report["hard_pass"])
        self.assertEqual(report["verdict"], "VALID_POOR_QUALITY")

    def test_snapshot_and_report_round_trip_through_json(self):
        s = self.clean()
        s.expected_rooms = {"Foyer": (3.0, 3.0, 1), "Living": (3.0, 3.0, 1), "Bed": (3.0, 3.0, 1)}
        again = LayoutSnapshot.from_dict(json.loads(json.dumps(s.to_dict())))
        self.assertEqual(again.to_dict(), s.to_dict())
        self.assertEqual(json.loads(to_json(evaluate(s)))["verdict"], "OK")


class PackageTests(unittest.TestCase):
    def test_validation_package_does_not_import_ortools(self):
        code = "import sys, testfit.validation; assert 'ortools' not in sys.modules"
        subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)

    def test_sample_matrix_is_well_formed(self):
        ids = [c.id for c in SAMPLE_CONFIGS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(1 <= c.floors <= 5 for c in SAMPLE_CONFIGS))
        self.assertEqual({c.road_access for c in SAMPLE_CONFIGS}, {"North", "South", "East", "West"})
        types = {c.building_type for c in SAMPLE_CONFIGS}
        self.assertTrue({"Duplex", "Rental / Multi-Unit Building"} <= types)
        self.assertIn(5, {c.floors for c in SAMPLE_CONFIGS})


if __name__ == "__main__":
    unittest.main()
