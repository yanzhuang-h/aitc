"""缺经验候选使用合成稳定周期验证，不启动训练或写运行经验。"""

import copy
import tempfile
import unittest

from lib.control_functions.global_processors.flow_control import process_flow_intersection
from lib.control_functions.global_processors.phase_adapter import allocate_phase_budget
from lib.data_ANS.flow_time_allocator import allocate_from_runtime_data
from lib.data_ANS.flow_allocator_shadow import record_shadow_comparison


ROAD = "1700240"


def config(phases=("UD", "LR"), lows=(20, 20), highs=(150, 150)):
    return {"phase": list(phases), "min_pass_time": list(lows), "max_pass_time": list(highs)}


class ColdStartTimingTests(unittest.TestCase):
    def setUp(self):
        self.cross = {ROAD: {
            "phase": {"1": "UD", "2": "LR"}, "Cycle": [[1, 2]],
            "LaneNo": {direction: {"1": "1B"} for direction in ("U", "D", "L", "R")},
        }}
        self.programs = {ROAD: {"1": config()}}
        self.extend = {1000 + offset: [{"CrossId": ROAD, "curStageNo": "1" if offset % 120 < 80 else "2"}]
                       for offset in range(600)}

    def evaluate(self, values=(40, 20, 10, 5), table=None, cross=None, programs=None, extend=None, road=ROAD):
        flow = {stamp: {"pass": {direction: [0, value] + [0] * 8
                                for direction, value in zip(("U", "D", "L", "R"), values)}}
                for stamp in (1000, 1599)}
        return allocate_from_runtime_data(
            road, flow, self.extend if extend is None else extend,
            experience_table={} if table is None else table,
            cross_info=self.cross if cross is None else cross,
            road_info=self.programs if programs is None else programs,
        )

    def test_empty_experience_changes_with_live_flow_inside_reference_budget(self):
        for values, expected in (((40, 20, 10, 5), [96, 24]),
                                 ((10, 5, 40, 20), [24, 96])):
            with self.subTest(values=values):
                result = self.evaluate(values)
                audit = result["runtime_input"]["cold_start"]
                self.assertEqual(audit["status"], "observed_cycle_flow_budget")
                self.assertEqual(audit["reference_phase_times"], [80, 40])
                self.assertEqual(audit["allocated_phase_times"], expected)
                self.assertEqual(audit["allocated_budget"], 120)
                self.assertEqual(result["direction_time_vector"], result["time_vector"][:8])
                plan, report = process_flow_intersection(
                    ROAD, result["time_vector"], self.programs[ROAD], 17,
                    lambda _road, state: state, lambda _road: {},
                )
                self.assertTrue(report["success"])
                self.assertEqual(plan[:2], expected)
                self.assertEqual(plan[8:], [0, 1])

    def test_two_stable_cycles_are_enough_for_runtime_reference(self):
        extend = {1000 + offset: [{"CrossId": ROAD,
                                  "curStageNo": "1" if offset % 150 < 100 else "2"}]
                  for offset in range(600)}
        result = self.evaluate(extend=extend)
        audit = result["runtime_input"]["cold_start"]
        self.assertEqual(audit["reference_cycle_count"], 2)
        self.assertEqual(audit["allocated_phase_times"], [120, 30])

    def test_effective_platform_limits_redistribute_saturated_phase(self):
        programs = copy.deepcopy(self.programs)
        programs[ROAD]["1"]["platform_max_pass_time"] = [90, 150]
        result = self.evaluate((1000, 500, 1, 1), programs=programs)
        audit = result["runtime_input"]["cold_start"]
        self.assertEqual(audit["allocated_phase_times"], [90, 30])
        self.assertEqual(audit["maximums"], [90, 150])

    def test_zero_direction_retains_observed_green_instead_of_losing_budget(self):
        result = self.evaluate((0, 0, 40, 20))
        audit = result["runtime_input"]["cold_start"]
        self.assertEqual(audit["allocated_phase_times"], [80, 40])
        self.assertIn(0, audit["held_phase_indexes"])
        self.assertEqual(result["times"]["U"], 80)
        self.assertEqual(result["times"]["D"], 80)

    def test_all_zero_flow_keeps_existing_fallback(self):
        result = self.evaluate((0, 0, 0, 0))
        self.assertEqual(result["runtime_input"]["cold_start"]["status"], "no_positive_controlled_flow")
        self.assertNotEqual(result["times"]["U"], 80)

    def test_usable_experience_and_input_objects_are_preserved(self):
        table = {ROAD: {direction: {"40": [0, 1000] + [0] * 8} for direction in ("L", "R")}}
        original = copy.deepcopy((table, self.cross, self.programs, self.extend))
        result = self.evaluate(table=table)
        self.assertEqual(result["times"]["L"], 40)
        self.assertEqual(result["times"]["R"], 40)
        self.assertEqual(result["decisions"]["L"]["status"], "matched_capacity_threshold")
        self.assertEqual(result["times"]["U"], 80)
        self.assertEqual((table, self.cross, self.programs, self.extend), original)

    def test_uncontrolled_right_turn_flow_cannot_take_more_green(self):
        base = self.evaluate()
        flow = {stamp: {"pass": {direction: [0, value, 100000 if direction == "R" else 0] + [0] * 7
                                for direction, value in zip(("U", "D", "L", "R"), (40, 20, 10, 5))}}
                for stamp in (1000, 1599)}
        cross = copy.deepcopy(self.cross)
        cross[ROAD]["LaneNo"]["R"]["2"] = "1C"
        result = allocate_from_runtime_data(
            ROAD, flow, self.extend, experience_table={}, cross_info=cross, road_info=self.programs,
        )
        self.assertEqual(result["time_vector"], base["time_vector"])

    def test_dedicated_left_flow_uses_same_base_vector_fallback_as_allocator(self):
        cross = copy.deepcopy(self.cross)
        cross[ROAD]["phase"]["1"] = "UDL"
        for direction in ("U", "D"):
            cross[ROAD]["LaneNo"][direction]["1"] = "1A"
        programs = {ROAD: {"1": config(("UDL", "LR"))}}
        result = self.evaluate(cross=cross, programs=programs)
        self.assertEqual(result["times"]["UTL"], 96)
        self.assertEqual(result["times"]["DTL"], 96)
        self.assertEqual(result["times"]["L"], 24)

    def test_bad_stage_or_fewer_than_two_stable_cycles_cannot_activate(self):
        examples = (
            {stamp: [{"CrossId": ROAD, "curStageNo": "0"}] for stamp in self.extend},
            dict(list(self.extend.items())[:300]),
        )
        for extend in examples:
            with self.subTest(seconds=len(extend)):
                result = self.evaluate(extend=extend)
                self.assertEqual(result["runtime_input"]["cold_start"]["status"], "insufficient_stable_stage_feedback")
                self.assertNotEqual(result["times"]["U"], 96)

    def test_no_matching_program_does_not_invent_phase_bounds(self):
        result = self.evaluate(programs={ROAD: {"1": config(("U", "D"), (20, 20), (150, 150))}})
        self.assertEqual(result["runtime_input"]["cold_start"]["status"], "no_matching_program_bounds")
        self.assertNotEqual(result["times"]["U"], 96)

    def test_19_uses_same_fallback_without_migrating_program_selection(self):
        road = "1700125"
        cross = {road: self.cross[ROAD]}
        programs = {road: {"0": config()}}
        extend = {stamp: [{"CrossId": road, "curStageNo": rows[0]["curStageNo"]}]
                  for stamp, rows in self.extend.items()}
        result = self.evaluate(cross=cross, programs=programs, extend=extend, road=road)
        self.assertEqual(result["times"]["U"], 96)
        plan, report = process_flow_intersection(
            road, result["time_vector"], programs[road], 17,
            lambda _road, state: state, lambda _road: {},
        )
        self.assertEqual(plan[:2], [96, 24])
        self.assertEqual(report["state"], "0")

    def test_historical_road_keeps_existing_fallback(self):
        road = "1300069"
        cross, programs = {road: self.cross[ROAD]}, {road: {"1": config()}}
        extend = {stamp: [{"CrossId": road, "curStageNo": rows[0]["curStageNo"]}]
                  for stamp, rows in self.extend.items()}
        result = self.evaluate(cross=cross, programs=programs, extend=extend, road=road)
        self.assertEqual(result["runtime_input"]["cold_start"]["status"], "not_needed")
        self.assertEqual(result["times"]["U"], 30)

    def test_shared_phase_with_usable_experience_keeps_connected_movements(self):
        from lib.data_ANS.cold_start_timing import observed_cycle_fallback
        phases = {"1": "UD", "2": "U", "3": "LR"}
        cycles = [{"pattern": ["1", "2", "3"],
                   "items": [{"duration": 60}, {"duration": 20}, {"duration": 40}]}
                  for _ in range(3)]
        decisions = self.evaluate()["decisions"]
        decisions["U"]["experience_profile"] = {"positive_capacity_points": 1}
        updates, audit = observed_cycle_fallback(
            cycles, {**self.cross[ROAD], "phase": phases},
            {"1": config(("UD", "U", "LR"), (20, 10, 20), (150, 150, 150))},
            {direction: [0, 10] + [0] * 8 for direction in decisions}, decisions,
        )
        self.assertEqual(set(updates), {"L", "R"})
        self.assertEqual(audit["cold_phase_indexes"], [2])

    def test_pedestrian_reference_is_not_lost_in_direction_projection(self):
        from lib.data_ANS.cold_start_timing import observed_cycle_fallback
        cycles = [{"pattern": ["1", "2", "3"], "items": [{"duration": 80}, {"duration": 40}, {"duration": 30}]}
                  for _ in range(3)]
        updates, audit = observed_cycle_fallback(
            cycles, {**self.cross[ROAD], "phase": {"1": "UD", "2": "LR", "3": "P"}},
            {}, {}, {},
        )
        self.assertEqual(updates, {})
        self.assertEqual(audit["status"], "non_vehicle_phase_requires_program_plan")

    def test_shadow_log_records_reference_and_flow_budget(self):
        flow = {stamp: {"pass": {direction: [0, value] + [0] * 8
                                for direction, value in zip(("U", "D", "L", "R"), (40, 20, 10, 5))}}
                for stamp in (1000, 1599)}
        with tempfile.TemporaryDirectory() as directory:
            record = record_shadow_comparison(
                ROAD, [0] * 10, flow, self.extend,
                experience_table={}, cross_info=self.cross, road_info=self.programs,
                log_directory=directory, runtime_mode="new",
            )
        self.assertEqual(record["selected_schedule_source"], "new")
        self.assertEqual(record["cold_start"]["allocated_phase_times"], [96, 24])
        self.assertEqual(record["decisions"]["U"]["fallback_source"], "observed_cycle_flow_budget")
        self.assertEqual(record["decisions"]["U"]["experience_point_count"], 0)
        self.assertEqual(record["decisions"]["U"]["table_green_time"], 0)

    def test_invalid_budget_is_rejected_and_zero_weight_gap_is_audited(self):
        with self.assertRaises(ValueError):
            allocate_phase_budget([float("nan"), 1], config(), 120)
        times, audit = allocate_phase_budget([0, 0], config(), 120)
        self.assertEqual(times, [20, 20])
        self.assertEqual(audit["unallocated_budget"], 80)


if __name__ == "__main__":
    unittest.main()
