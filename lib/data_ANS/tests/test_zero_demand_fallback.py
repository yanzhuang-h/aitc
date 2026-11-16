import copy
from datetime import datetime, timezone
import os
import tempfile
import unittest
from unittest import mock

from lib.control_functions.global_processors.flow_control import process_flow_intersection
from lib.data_ANS.flow_allocator_shadow import record_shadow_comparison
from lib.data_ANS.flow_time_allocator import allocate_green_times


def vector(count=0, lane=1):
    values = [0] * 10
    values[lane] = count
    return values


class ZeroDemandFallbackTests(unittest.TestCase):
    def setUp(self):
        self.cross = {"1700240": {"LaneNo": {"U": {"1": "1B", "2": "1A"}}}}
        self.table = {"1700240": {
            "L": {"71": vector(60)},
            "UTL": {"60": vector(40, lane=2)},
        }}

    def allocate(self, flow, **kwargs):
        return allocate_green_times(
            "1700240", flow, self.table, self.cross, active_directions={"U", "UTL"},
            **kwargs,
        )

    def test_zero_demand_does_not_borrow_related_or_road_long_experience(self):
        before_table, before_cross = copy.deepcopy(self.table), copy.deepcopy(self.cross)
        baseline = self.allocate({"U": vector()})
        changed = self.allocate({"U": vector()}, zero_demand_fallback=True)
        self.assertEqual(baseline["times"]["U"], 60)
        self.assertEqual(changed["times"]["U"], 30)
        self.assertEqual(changed["times"]["UTL"], 30)
        self.assertEqual(changed["decisions"]["U"]["status"], "fallback_zero_controlled_demand")
        self.assertEqual(self.table, before_table)
        self.assertEqual(self.cross, before_cross)

    def test_shorter_existing_zero_demand_point_is_preserved(self):
        self.table["1700240"]["U"] = {"20": vector(10), "70": vector(50)}
        result = self.allocate({"U": vector()}, zero_demand_fallback=True)
        self.assertEqual(result["times"]["U"], 20)
        self.assertEqual(result["decisions"]["U"]["status"], "zero_demand_minimum_time")

    def test_long_own_zero_demand_point_uses_existing_safe_time(self):
        self.table["1700240"]["U"] = {"71": vector(60)}
        result = self.allocate({"U": vector()}, zero_demand_fallback=True)
        self.assertEqual(result["times"]["U"], 30)
        self.assertEqual(result["decisions"]["U"]["capacity_at_selected_time"], 0)
        self.assertEqual(result["decisions"]["U"]["threshold_at_selected_time"], 0)

    def test_positive_controlled_flow_preserves_lookup_and_fallback(self):
        for own_points in [{}, {"50": vector(50), "71": vector(100)}]:
            self.table["1700240"]["U"] = own_points
            for count in [1, 30, 1000]:
                with self.subTest(own_points=own_points, count=count):
                    flow = {"U": vector(count)}
                    before = self.allocate(flow)
                    after = self.allocate(flow, zero_demand_fallback=True)
                    self.assertEqual(after["times"]["U"], before["times"]["U"])
                    self.assertEqual(after["decisions"]["U"], before["decisions"]["U"])

    def test_uncontrolled_flow_does_not_count_as_controlled_demand(self):
        self.cross["1700240"]["LaneNo"]["U"]["3"] = "1C"
        result = self.allocate({"U": vector(9999, lane=3)}, zero_demand_fallback=True)
        self.assertEqual(result["decisions"]["U"]["requested_flow"], 0)
        self.assertEqual(result["times"]["U"], 30)

    def test_empty_table_retains_safe_time_and_inactive_directions(self):
        self.table = {"1700240": {}}
        result = self.allocate({"U": vector()}, zero_demand_fallback=True)
        self.assertEqual(result["times"]["U"], 30)
        self.assertEqual(result["times"]["D"], 0)

    def test_custom_safe_time_limits_and_explicit_left_turn_extra(self):
        result = self.allocate(
            {"U": vector()}, zero_demand_fallback=True,
            safe_fallback_green_time=27, min_green_time=35, max_green_time=40,
            left_turn_extra_seconds=8,
        )
        self.assertEqual(result["times"]["U"], 35)
        self.assertEqual(result["times"]["UTL"], 40)

    def test_platform_minimums_still_apply_after_zero_demand_fallback(self):
        result = self.allocate({"U": vector()}, zero_demand_fallback=True)
        config = {"1": {
            "phase": ["UD", "LR"],
            "min_pass_time": [20, 20],
            "platform_min_pass_time": [45, 35],
            "max_pass_time": [200, 200],
            "platform_max_pass_time": [200, 200],
        }}
        plan, report = process_flow_intersection(
            "1700240", result["time_vector"], config, 14,
            lambda road, state: state, lambda road: {},
        )
        self.assertTrue(report["success"])
        self.assertEqual(plan[:2], [45, 35])

    def test_runtime_enables_policy_only_for_49_group(self):
        with mock.patch.dict(os.environ, {
            "AITC_FLOW_ALLOCATOR_PILOT_ROADS": "",
            "AITC_FLOW_ALLOCATOR_SHADOW_ROADS": "",
            "AITC_FLOW_ALLOCATOR_SHADOW_ENABLED": "1",
        }), tempfile.TemporaryDirectory() as directory:
            for road_id, expected_zero_time in [
                ("1700240", 30), ("1700125", 60), ("1300069", 60),
            ]:
                with self.subTest(road_id=road_id):
                    cross = {road_id: {
                        "phase": {"1": "UD"}, "Cycle": [],
                        "LaneNo": {"U": {"1": "1B"}, "D": {"1": "1B"}},
                    }}
                    table = {road_id: {"U": {"60": vector(100)}}}
                    flow = {"1000": {"pass": {"U": vector(10), "D": vector()}}}
                    extend = {timestamp: [{"CrossId": road_id, "curStageNo": "1"}]
                              for timestamp in range(1000, 1600)}
                    result = record_shadow_comparison(
                        road_id, [60] * 8 + [0, 0], flow, extend,
                        experience_table=table, cross_info=cross, log_directory=directory,
                        observed_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
                        runtime_mode="new",
                    )
                    self.assertEqual(result["status"], "ok")
                    self.assertEqual(result["selected_schedule_source"], "new")
                    self.assertEqual(result["new_schedule"][0], 60)
                    self.assertEqual(result["new_schedule"][1], expected_zero_time)


if __name__ == "__main__":
    unittest.main()
