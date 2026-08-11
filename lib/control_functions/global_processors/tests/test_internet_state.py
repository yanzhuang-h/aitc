import unittest

from lib.control_functions.global_processors.internet_state import (
    calculate_internet_direction_demand,
    select_internet_control_state,
    apply_internet_phase_demand,
    update_internet_road_state,
)
from lib.control_functions.global_processors.internet_single_control import (
    process_internet_intersection,
)


class InternetStateTests(unittest.TestCase):
    def test_aggregates_directional_online_observations(self):
        state = {999: {"kept": True}}
        online_data = {
            "rid-1": {
                2: [{"jam_state_no": 0, "speed": 10}],
                1: [{"jam_state_no": 2, "speed": 30}],
            }
        }
        mapping = {"rid-1": {101: "U"}}

        result = update_internet_road_state(state, online_data, {101}, mapping)

        self.assertIs(result, state)
        self.assertEqual(state[999], {"kept": True})
        self.assertEqual(state[101]["U"], [2, 1, 17.5, 0, 0])

    def test_skips_malformed_records_like_legacy_coordinate(self):
        state = {}
        result = update_internet_road_state(
            state,
            {"rid-1": {1: [{}]}},
            {101},
            {"rid-1": {101: "U"}},
        )
        self.assertEqual(result[101]["U"], [0, 0, 20, 0, 0])

    def test_direction_demand_keeps_congestion_penalties(self):
        direction_state = {
            "L": [1, 0, 20, 1, 0],
            "R": [1, 0, 20, 0, 0],
            "U": [1, 0, 20, 0, 0],
            "D": [1, 0, 20, 0, 0],
        }
        demand = calculate_internet_direction_demand(
            direction_state,
            [10, 10, 10, 10],
            lambda _state: 0,
        )
        self.assertEqual(demand, {"L": 25, "R": 10, "U": 2, "D": 2})

    def test_selects_available_compound_state(self):
        config = {str(index): {} for index in (0, 1, 11)}
        self.assertEqual(select_internet_control_state(
            "100", {"L": 0, "R": 20, "U": 20, "D": 0}, config, 12), "11")

    def test_overnight_fallback(self):
        self.assertEqual(select_internet_control_state(
            "100", {"L": 0, "R": 0, "U": 0, "D": 0}, {"0": {}, "5": {}}, 3), "5")

    def test_phase_demand_helper_updates_base_plan(self):
        plan = apply_internet_phase_demand(
            [10] * 8, ["L", "R", "UD", "LR", "P", "P", "P", "P"], [1] * 8,
            {"L": 4, "R": 8, "U": 6, "D": 2},
        )
        self.assertEqual(plan[:4], [10, 14, 16, 14])

    def test_processes_complete_internet_intersection(self):
        config = {"0": {
            "min_pass_time": [10] * 10,
            "phase": ["L", "R", "UD", "LR", "P", "P", "P", "P"],
            "phase_weight": [1] * 8,
        }}
        plan, report = process_internet_intersection(
            "100", {key: [0, 0, 20, 0, 0] for key in "LRUD"},
            [4, 8, 6, 2], config, 12, lambda _value: 0,
            lambda _cross_id, state: state,
        )
        self.assertTrue(report["success"])
        self.assertEqual(plan[:4], [10, 14, 16, 14])
        self.assertEqual(plan[9], 0)

    def test_reports_invalid_state_configuration(self):
        plan, report = process_internet_intersection(
            "100", {key: [0, 0, 20, 0, 0] for key in "LRUD"},
            [0, 0, 0, 0], {}, 12, lambda _value: 0,
            lambda _cross_id, state: state,
        )
        self.assertIsNone(plan)
        self.assertFalse(report["success"])
        self.assertIn("KeyError", report["error"])


if __name__ == "__main__":
    unittest.main()
