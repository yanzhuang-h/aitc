import json
from pathlib import Path
import unittest

from lib.road_groups import TONGZHOU_19, TONGZHOU_49, road_group
from lib.control_functions.global_processors.flow_control import (
    process_flow_intersection, select_flow_control_state,
)
from lib.control_functions.global_processors.phase_adapter import (
    allocate_phase_times, phase_bounds,
)

ROOT = Path(__file__).resolve().parents[4]


def config(phases, lows=None, highs=None):
    return {"phase": phases + [0] * (10-len(phases)),
            "min_pass_time": lows or [5] * len(phases),
            "max_pass_time": highs or [200] * len(phases)}


class TongzhouFlowTests(unittest.TestCase):
    def test_batch_membership_matches_onboarding_registry(self):
        registered = json.loads((ROOT / "lib/plan_id_overrides.json").read_text())
        self.assertEqual(set(registered), TONGZHOU_49)
        self.assertEqual(len(TONGZHOU_19), 19)
        self.assertTrue(TONGZHOU_19.isdisjoint(TONGZHOU_49))
        self.assertEqual(road_group("1700125"), "19")
        self.assertEqual(road_group(1700267), "49")
        self.assertIsNone(road_group("1300069"))

    def test_platform_ids_are_not_legacy_direction_selectors(self):
        states = {"1": config(["UD", "LR"]), "2": config(["U", "D", "LR"])}
        for direction in ("U", "D", "L", "R"):
            demand = dict.fromkeys(("U", "D", "L", "R"), 0)
            demand[direction] = 100
            self.assertEqual(select_flow_control_state("1700267", demand, states, 17), "1")

    def test_all_49_configs_select_existing_default_and_convert(self):
        roads = json.loads((ROOT / "lib/road_info.json").read_text())
        for rid in sorted(TONGZHOU_49):
            with self.subTest(road=rid):
                source = [80, 60, 100, 70, 20, 15, 25, 20, 0, 0]
                result, report = process_flow_intersection(
                    rid, source, roads[rid], 17,
                    lambda road, state: state, lambda road: {})
                self.assertTrue(report["success"], report)
                self.assertEqual(report["state"], "1")
                phases, lows, highs = phase_bounds(roads[rid]["1"])
                self.assertEqual(len(result), 10)
                self.assertEqual(result[9], 1)
                self.assertEqual(result[len(phases):9], [0] * (9-len(phases)))
                for value, low, high in zip(result, lows, highs):
                    self.assertLessEqual(low, value)
                    self.assertLessEqual(value, high)
                self.assertEqual(source, [80, 60, 100, 70, 20, 15, 25, 20, 0, 0])

    def test_single_release_and_shared_phase_do_not_duplicate_demand(self):
        times, report = allocate_phase_times(
            {"U": 80, "D": 60, "UTL": 20}, config(["U", "UD"]))
        self.assertEqual(times, [20, 60])
        self.assertEqual(report["served_movement_times"], {"U": 80, "D": 60, "UTL": 20})
        self.assertEqual(report["unmet_movement_times"], {})

    def test_platform_order_controls_output(self):
        times, _ = allocate_phase_times(
            {"U": 40, "D": 30, "L": 80, "R": 70}, config(["LR", "UD"]))
        self.assertEqual(times, [80, 40])

    def test_repeated_phases_share_total_demand(self):
        times, _ = allocate_phase_times(
            {"L": 100, "R": 80}, config(["LR", "LR"]))
        self.assertEqual(times, [50, 50])

    def test_dedicated_left_and_single_release_use_training_incidence(self):
        times, report = allocate_phase_times(
            {"R": 55, "L": 25, "RTL": 90, "LTL": 40},
            config(["LR", "R", "LRL"]))
        self.assertEqual(sum(times), 115)
        self.assertEqual(times[0], 25)
        self.assertGreaterEqual(times[0] + times[1], 55)
        self.assertGreaterEqual(times[1] + times[2], 90)
        self.assertGreaterEqual(times[2], 40)
        self.assertEqual(report["unmet_movement_times"], {})

    def test_uses_tighter_platform_max_and_reports_unserved_demand(self):
        state = config(["UD"], [10], [200])
        state["platform_max_pass_time"] = [50]
        times, report = allocate_phase_times({"U": 100, "D": 80}, state)
        self.assertEqual(times, [50])
        self.assertEqual(report["unmet_movement_times"], {"U": 50, "D": 30})

    def test_invalid_phase_layout_or_bounds_fails_explicitly(self):
        for state in (config(["UNKNOWN"]), config(["UD", 0, "LR"]),
                      config(["UD"], [60], [50])):
            with self.subTest(state=state), self.assertRaises(ValueError):
                phase_bounds(state)

    def test_forced_program_is_honored_and_uses_its_own_order(self):
        roads = {"1": config(["UD", "LR"]), "2": config(["LR", "UD"])}
        plan, report = process_flow_intersection(
            "1700267", [40,30,80,70,0,0,0,0,0,0], roads, 17,
            lambda road, state: "2", lambda road: {})
        self.assertTrue(report["success"])
        self.assertEqual(plan[:2], [80,40])
        self.assertEqual(plan[9], 2)

    def test_empty_candidate_uses_bounded_default_timetable(self):
        plan, report = process_flow_intersection(
            "2705189", [0]*10, {"1": config(["LR", "UD"])}, 17,
            lambda road, state: state, lambda road: {"17": [30,40]+[0]*8})
        self.assertEqual(plan, [30,40]+[0]*7+[1])
        self.assertEqual(report["fallback"], "time_schedule")

    def test_forced_program_never_reuses_different_layout_timetable(self):
        plan, report = process_flow_intersection(
            "2705189", [0]*10,
            {"1": config(["LR", "UD"]), "2": config(["U", "D", "LR"])}, 17,
            lambda road, state: "2", lambda road: self.fail("wrong program timetable"))
        self.assertTrue(report["success"])
        self.assertEqual(plan[:3], [5,5,5])
        self.assertEqual(report["fallback"], "forced_program_minimums")

    def test_formatter_preserves_selected_platform_program(self):
        from runtime.result_formatter import _plan_id_for
        self.assertEqual(_plan_id_for("1700267", 2), 2)
        self.assertEqual(_plan_id_for("1700267", 0), 1)

    def test_forced_program_layout_survives_actual_payload_formatting(self):
        import Lambdas
        from runtime.result_formatter import format_result
        states = {"1": config(["UD", "LR"]), "2": config(["LR", "UD"])}
        plan, report = process_flow_intersection(
            "1700267", [40,30,80,70,0,0,0,0,0,0], states, 17,
            lambda road, state: "2", lambda road: {})
        self.assertTrue(report["success"])
        payload = format_result("1700267", plan, [0]*4, [], lambdas_module=Lambdas)
        logic = payload["additional"]["tlLogic"]
        self.assertEqual(logic["programID"], 2)
        self.assertEqual([phase["duration"] for phase in logic["phase"]], [80,40])

    def test_invalid_program_does_not_return_direction_vector(self):
        plan, report = process_flow_intersection(
            "2705189", [30]*8+[0,0], {"1": config(["UD", "LR"])}, 17,
            lambda road, state: "9", lambda road: {})
        self.assertFalse(report["success"])
        self.assertEqual(plan, [0]*10)
        self.assertIn("missing", report["error"])

    def test_old_19_1700125_retains_existing_rules(self):
        roads = json.loads((ROOT / "lib/road_info.json").read_text())
        plan, report = process_flow_intersection(
            "1700125", [30,30,4,4,0,0,30,30,0,0], roads["1700125"], 16,
            lambda road, state: state, lambda road: {})
        self.assertEqual(plan[:3], [55,32,40])
        self.assertEqual(report["road_group"], "19")


if __name__ == "__main__":
    unittest.main()
