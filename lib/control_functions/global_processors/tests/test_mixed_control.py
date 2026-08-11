import unittest

from lib.control_functions.global_processors.mixed_control import (
    calculate_mixed_direction_demand,
    generate_mixed_phase_plan,
    select_mixed_control_state,
    process_mixed_intersection,
)
from lib.control_functions.global_processors.flow_control import select_flow_control_state
from lib.control_functions.global_processors.flow_control import generate_flow_phase_plan
from lib.control_functions.global_processors.flow_control import process_flow_intersection


class MixedControlTests(unittest.TestCase):
    def test_combines_existing_plan_and_internet_adjustments(self):
        state = {key: [1, 0, 20, 0, 0] for key in "LRUD"}
        plan = [30, 40, 10, 20, 5, 6, 7, 8, 0, 0]
        result = calculate_mixed_direction_demand(
            state, plan, lambda _state: 2
        )
        self.assertEqual(result, {
            "L": 12, "R": 22, "U": 32, "D": 42,
            "UTL": 5, "DTL": 6, "LTL": 7, "RTL": 8,
        })

    def test_preserves_cross_direction_congestion_penalty(self):
        state = {key: [1, 0, 20, 0, 0] for key in "LRUD"}
        state["L"][3] = 1
        result = calculate_mixed_direction_demand(
            state, [30, 40, 10, 20, 0, 0, 0, 0, 0, 0], lambda _state: 0
        )
        self.assertEqual(result["L"], 25)
        self.assertEqual(result["U"], 22)
        self.assertEqual(result["D"], 32)

    def test_selects_jam_compound_before_direction_difference(self):
        state = {key: [1, 0, 20, 0, 0] for key in "LRUD"}
        state["R"][3] = state["U"][3] = 1
        result = select_mixed_control_state(
            state, {"L": 10, "R": 10, "U": 10, "D": 10}, {"0": {}, "11": {}}, 12
        )
        self.assertEqual(result, "11")

    def test_generates_bounded_mixed_phase_plan(self):
        config = {
            "phase": ["UD", "LR", "L", "R", "UDL", "LRL", "P", "P"],
            "platform_min_pass_time": [5] * 8,
            "max_pass_time": [60] * 8,
        }
        demand = {"L": 20, "R": 10, "U": 30, "D": 15,
                  "UTL": 8, "DTL": 9, "LTL": 6, "RTL": 7}
        plan = generate_mixed_phase_plan([0] * 10, demand, config)
        self.assertEqual(plan[:6], [30, 5, 20, 15, 9, 7])

    def test_flow_special_hour_override_preserves_legacy_tuple_state(self):
        state = select_flow_control_state(
            "1300364", {"L": 0, "R": 0, "U": 0, "D": 0}, {"0": {}, "4": {}}, 7
        )
        self.assertEqual(state, ("4",))

    def test_flow_phase_generator_handles_half_and_pedestrian_phases(self):
        config = {"phase": ["UD1", "LR1", "U", "D", "P", "P", "P", "P"],
                  "platform_min_pass_time": [5] * 8, "max_pass_time": [60] * 8}
        plan = generate_flow_phase_plan(
            [0] * 10, {"L": 10, "R": 20, "U": 30, "D": 10,
                       "UTL": 4, "DTL": 5, "LTL": 6, "RTL": 7}, config)
        self.assertEqual(plan[0:4], [15, 10, 30, 10])

    def test_flow_phase_generator_clamps_special_turn_phases(self):
        config = {"phase": ["LRL", "UDL", "L", "R", "UD", "LR", "P", "P"],
                  "platform_min_pass_time": [8] * 8, "max_pass_time": [20] * 8}
        plan = generate_flow_phase_plan(
            [0] * 10, {"L": 40, "R": 10, "U": 30, "D": 20,
                       "UTL": 18, "DTL": 4, "LTL": 16, "RTL": 5}, config)
        self.assertEqual(plan[:6], [18.0, 19.5, 20, 15, 20, 8])

    def test_flow_entry_uses_schedule_for_zero_plan(self):
        plan, report = process_flow_intersection(
            "100", [0] * 10, {"0": {}}, 12,
            lambda _cross, state: state,
            lambda _cross: {"12": [1] * 10},
        )
        self.assertTrue(report["success"])
        self.assertEqual(report["fallback"], "time_schedule")
        self.assertEqual(plan, [1] * 10)

    def test_mixed_entry_uses_schedule_for_zero_plan(self):
        plan, report = process_mixed_intersection(
            "100", [0] * 10, {key: [0, 0, 20, 0, 0] for key in "LRUD"},
            {"0": {}}, 12, lambda _state: 0,
            lambda _cross, state: state,
            lambda _cross: {"12": [2] * 10},
        )
        self.assertTrue(report["success"])
        self.assertEqual(report["fallback"], "time_schedule")
        self.assertEqual(plan, [2] * 10)

    def test_mixed_entry_allocates_using_forced_state(self):
        state_config = {
            "0": {"phase": ["P"] * 8, "platform_min_pass_time": [1] * 8, "max_pass_time": [60] * 8},
            "2": {"phase": ["LR", "P", "P", "P", "P", "P", "P", "P"], "platform_min_pass_time": [3] * 8, "max_pass_time": [60] * 8},
        }
        plan, report = process_mixed_intersection(
            "100", [10, 10, 10, 30, 0, 0, 0, 0, 0, 0],
            {key: [0, 0, 20, 0, 0] for key in "LRUD"}, state_config, 12,
            lambda _state: 0, lambda _cross, _state: "2",
            lambda _cross: {},
        )
        self.assertTrue(report["success"])
        self.assertEqual(report["state"], "2")
        self.assertGreaterEqual(plan[0], 3)

    def test_flow_entry_allocates_using_forced_state(self):
        config = {
            "0": {"phase": ["P"] * 8, "platform_min_pass_time": [1] * 8, "max_pass_time": [60] * 8},
            "2": {"phase": ["LR1"] + ["P"] * 7, "platform_min_pass_time": [3] * 8, "max_pass_time": [60] * 8},
        }
        plan, report = process_flow_intersection(
            "100", [10, 10, 10, 30, 0, 0, 0, 0, 0, 0], config, 12,
            lambda _cross, _state: "2", lambda _cross: {},
        )
        self.assertTrue(report["success"])
        self.assertEqual(report["state"], "2")
        self.assertEqual(plan[0], 15)


if __name__ == "__main__":
    unittest.main()
