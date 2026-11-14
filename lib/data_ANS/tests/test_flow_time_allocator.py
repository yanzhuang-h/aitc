import unittest

from lib.data_ANS.flow_time_allocator import (
    aggregate_10min_flow,
    allocate_from_runtime_data,
    allocate_green_times,
    chuli_shuju_new,
    normalize_runtime_extend,
)


def _vector(**values):
    result = [0] * 10
    for lane, value in values.items():
        result[int(lane)] = value
    return result


def _runtime_vector(**values):
    result = [0] * 7
    for lane, value in values.items():
        result[int(lane)] = value
    return result


def _extend(road_id, stages, start=1000):
    result = {}
    for offset, stage in enumerate(stages):
        timestamp = start + offset
        result[float(timestamp)] = [{
            "CrossId": road_id,
            "curStageNo": str(stage),
            "curStageRemainLen": "0",
            "time": timestamp * 1000,
        }]
    return result


class FlowTimeAllocatorTests(unittest.TestCase):
    def setUp(self):
        self.cross_info = {
            "1300069": {
                "LaneNo": {
                    "U": {
                        "1": "1A",
                        "2": "1B",
                        "3": "1C",
                    }
                }
            }
        }
        self.table = {
            "1300069": {
                "U": {
                    "30": _vector(**{"2": 20, "3": 100}),
                    "50": _vector(**{"2": 40, "3": 100}),
                },
                "UTL": {
                    "20": _vector(**{"1": 10}),
                    "40": _vector(**{"1": 30}),
                },
            }
        }

    def test_timebase_audit_does_not_change_stage_clock_or_conflicts(self):
        start = 1794326400
        received = {
            start + 100.1: [{"CrossId": "1300069", "curStageNo": "1", "time": start * 1000},
                           {"CrossId": "1300069", "curStageNo": "2", "time": (start + 1) * 1000}],
            start + 101.1: [{"CrossId": "1300069", "curStageNo": "2", "time": (start + 2) * 1000}],
        }
        stages, report = normalize_runtime_extend("1300069", received)
        self.assertEqual(stages, {start + 100: "-1", start + 101: "2"})
        self.assertEqual(report["coverage_ratio"], 0.5)
        self.assertEqual(report["observed_seconds"], 2)
        audit = report["timebase"]
        self.assertEqual(audit["timestamp_basis"], "mapping_key")
        self.assertEqual(audit["comparison_time_field"], "payload.time")
        self.assertEqual(audit["comparison_time_semantics"], "unverified_payload_timestamp")
        self.assertEqual(audit["payload_time_valid_records"], 3)
        self.assertEqual(audit["payload_time_observed_seconds"], 3)
        self.assertEqual(audit["payload_time_span_seconds"], 3)
        self.assertEqual(audit["key_minus_payload_time_min_seconds"], 99)
        self.assertEqual(audit["key_minus_payload_time_max_seconds"], 100)

    def test_time_audit_includes_invalid_stage_records_for_matching_road(self):
        start = 1794326400
        stages, report = normalize_runtime_extend("1300069", {
            start: [{"CrossId": "1300069", "curStageNo": "bad", "time": (start - 5) * 1000},
                    {"CrossId": "another", "curStageNo": "1", "time": (start - 100) * 1000},
                    "invalid payload"],
        })
        self.assertEqual(stages, {})
        self.assertEqual(report["invalid_stage_records"], 1)
        self.assertEqual(report["timebase"]["payload_time_valid_records"], 1)
        self.assertEqual(report["timebase"]["key_minus_payload_time_min_seconds"], 5)
        self.assertEqual(report["timebase"]["key_minus_payload_time_max_seconds"], 5)
        self.assertEqual(report["timebase"]["payload_scope"], "matching_road_with_valid_mapping_key")

    def test_invalid_or_missing_payload_clock_cannot_change_selection(self):
        missing = _extend("1300069", [1] * 600)
        malformed = _extend("1300069", [1] * 600)
        for index, records in enumerate(malformed.values()):
            records[0]["time"] = [None, "invalid", 10**400][index % 3]
        for records in missing.values():
            records[0].pop("time")
        kwargs = {"experience_table": self.table,
                  "cross_info": {"1300069": {"phase": {"1": "U"}, "LaneNo": {"U": {"2": "1B"}}}}}
        flow = {"1000": {"pass": {"U": _runtime_vector(**{"2": 15})}}}
        baseline = allocate_from_runtime_data("1300069", flow, missing, **kwargs)
        result = allocate_from_runtime_data("1300069", flow, malformed, **kwargs)
        for field in ["time_vector", "decisions", "flow_10min"]:
            self.assertEqual(result[field], baseline[field])
        self.assertEqual(result["runtime_input"]["quality_passed"], baseline["runtime_input"]["quality_passed"])
        audit = result["runtime_input"]["extend"]["timebase"]
        self.assertEqual(audit["payload_time_missing_records"], 200)
        self.assertEqual(audit["payload_time_invalid_records"], 400)

    def test_aggregates_timestamp_pass_map(self):
        values, stats = aggregate_10min_flow({
            "100": {"pass": {"U": _runtime_vector(**{"2": 3})}},
            "200": {"pass": {"U": _runtime_vector(**{"2": 4})}},
        })

        self.assertEqual(values["U"][2], 7)
        self.assertEqual(len(values["U"]), 10)
        self.assertEqual(stats["input_mode"], "timestamp_pass_map")

    def test_controlled_lane_demand_ignores_uncontrolled_right_turn(self):
        result = allocate_green_times(
            "1300069",
            {"U": _vector(**{"2": 15, "3": 999}), "UTL": _vector(**{"1": 8})},
            self.table,
            self.cross_info,
        )

        self.assertEqual(result["times"]["U"], 30)
        self.assertEqual(result["decisions"]["U"]["requested_flow"], 15)
        self.assertEqual(result["decisions"]["U"]["lane_indexes"], [2])
        self.assertEqual(result["decisions"]["U"]["status"], "matched_capacity_threshold")

    def test_left_turn_and_inactive_direction_are_explicit(self):
        result = allocate_green_times(
            "1300069",
            {"U": _vector(**{"2": 0}), "UTL": _vector(**{"1": 25})},
            self.table,
            self.cross_info,
            active_directions={"U": True, "UTL": True},
            left_turn_extra_seconds=6,
        )

        self.assertEqual(result["times"]["UTL"], 46)
        self.assertEqual(result["times"]["D"], 0)
        self.assertEqual(result["decisions"]["D"]["status"], "inactive")
        self.assertEqual(len(result["time_vector"]), 10)
        self.assertEqual(len(result["direction_time_vector"]), 8)

    def test_over_capacity_uses_the_largest_available_table_time(self):
        result = allocate_green_times(
            "1300069",
            {"U": _vector(**{"2": 50})},
            self.table,
            self.cross_info,
        )

        decision = result["decisions"]["U"]
        self.assertEqual(result["times"]["U"], 50)
        self.assertEqual(decision["status"], "over_capacity_at_max_time")

    def test_runtime_three_argument_input_uses_full_window_flow(self):
        cross_info = {
            "1300069": {
                "phase": {"1": "U"},
                "LaneNo": {"U": {"1": "1A", "2": "1B"}},
                "Cycle": [],
            }
        }
        flow = {
            "1000": {"pass": {"U": _runtime_vector(**{"2": 7})}},
            "1599": {"pass": {"U": _runtime_vector(**{"2": 8})}},
        }
        extend = {
            1000.1: [{"CrossId": "1300069", "curStageNo": "1"}],
            1599.1: [{"CrossId": "1300069", "curStageNo": "1"}],
        }

        result = allocate_from_runtime_data(
            "1300069",
            flow,
            extend,
            experience_table=self.table,
            cross_info=cross_info,
        )

        self.assertEqual(result["runtime_input"]["normalization_mode"], "full_10min_window")
        self.assertEqual(result["flow_10min"]["U"][2], 15)
        self.assertEqual(result["decisions"]["U"]["requested_flow"], 15)
        self.assertEqual(result["times"]["U"], 30)
        self.assertEqual(len(result["time_vector"]), 10)

    def test_runtime_left_turn_reads_1a_lane_from_base_direction(self):
        cross_info = {
            "1300069": {
                "phase": {"1": "U"},
                "LaneNo": {"U": {"1": "1A", "2": "1B"}},
                "Cycle": [],
            }
        }
        flow = {
            "1000": {"pass": {"U": _runtime_vector(**{"1": 8})}},
        }
        extend = _extend("1300069", [1] * 600)

        result = allocate_from_runtime_data(
            "1300069",
            flow,
            extend,
            experience_table=self.table,
            cross_info=cross_info,
        )

        self.assertEqual(result["decisions"]["UTL"]["requested_flow"], 8)
        self.assertEqual(result["decisions"]["UTL"]["lane_indexes"], [1])
        self.assertEqual(result["times"]["UTL"], 20)

    def test_extend_is_evidence_and_cannot_zero_flow_direction(self):
        cross_info = {
            "1300069": {
                "phase": {"1": "U", "2": "UDL", "3": "LR"},
                "LaneNo": {
                    "U": {"1": "1A", "2": "1B"},
                    "L": {"2": "1B"},
                    "R": {"2": "1B"},
                },
                "Cycle": [],
            }
        }
        table = {
            "1300069": {
                "U": {"30": _vector(**{"2": 20})},
                "UTL": {"20": _vector(**{"1": 10})},
                "L": {"30": _vector(**{"2": 20})},
                "R": {"30": _vector(**{"2": 20})},
            }
        }
        # The stage stream only reports LR. U still has real flow and must
        # remain active; extend is evidence, not a flow-direction gate.
        flow = {
            "1000": {"pass": {"U": _runtime_vector(**{"1": 4, "2": 5})}},
        }
        extend = _extend("1300069", [3] * 600)

        result = allocate_from_runtime_data(
            "1300069",
            flow,
            extend,
            experience_table=table,
            cross_info=cross_info,
        )

        self.assertEqual(result["runtime_input"]["extend_directions"], ["L", "R"])
        self.assertEqual(
            result["runtime_input"]["flow_directions"],
            ["U", "UTL"],
        )
        self.assertGreater(result["times"]["U"], 0)
        self.assertGreater(result["times"]["UTL"], 0)
        self.assertGreater(result["times"]["L"], 0)
        self.assertGreater(result["times"]["R"], 0)

    def test_missing_table_point_uses_nonzero_safe_fallback(self):
        cross_info = {
            "1300069": {
                "phase": {},
                "LaneNo": {"U": {"2": "1B"}},
                "Cycle": [],
            }
        }
        flow = {
            "1000": {"pass": {"U": _runtime_vector(**{"2": 3})}},
        }
        extend = _extend("1300069", [1] * 600)

        result = allocate_from_runtime_data(
            "1300069",
            flow,
            extend,
            experience_table={"1300069": {}},
            cross_info=cross_info,
            safe_fallback_green_time=27,
        )

        decision = result["decisions"]["U"]
        self.assertEqual(result["times"]["U"], 27)
        self.assertEqual(decision["status"], "fallback_missing_experience_points")
        self.assertEqual(decision["fallback_source"], "safe_fallback_time")

    def test_extend_active_uncontrolled_direction_uses_safe_time(self):
        result = allocate_green_times(
            "1700125",
            {"U": _vector(**{"1": 50})},
            {"1700125": {"U": {"22": _vector(**{"1": 20})}}},
            {"1700125": {"LaneNo": {"U": {"1": "3A"}}}},
            active_directions={"U"},
            safe_fallback_green_time=26,
        )

        decision = result["decisions"]["U"]
        self.assertEqual(result["times"]["U"], 26)
        self.assertEqual(decision["requested_flow"], 0)
        self.assertEqual(
            decision["status"],
            "fallback_no_controlled_capacity_lanes",
        )
        self.assertEqual(decision["fallback_source"], "safe_fallback_time")
        self.assertEqual(decision["excluded_non_capacity_lanes"], {"1": "3A"})

    def test_direction_vector_order_is_fixed_and_legacy_slots_are_reserved(self):
        result = allocate_green_times(
            "1300069",
            {"U": _vector(**{"2": 1})},
            self.table,
            self.cross_info,
        )

        self.assertEqual(
            result["direction_time_vector"],
            [
                result["times"][direction]
                for direction in ("U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL")
            ],
        )
        self.assertEqual(
            result["time_vector"][-2:],
            [0, 0],
        )

    def test_partial_runtime_window_scales_complete_cycles_to_10min(self):
        cross_info = {
            "1300069": {
                "phase": {"1": "U", "2": "U", "9": "P"},
                "LaneNo": {"U": {"1": "1A", "2": "1B"}},
                "Cycle": [[1, 2]],
            }
        }
        # Stage 9 on both edges makes the two 1->2 cycles fully bounded.
        stages = [9] + [1] * 5 + [2] * 5 + [1] * 5 + [2] * 5 + [9]
        extend = _extend("1300069", stages)
        flow = {
            "1005": {"pass": {"U": _runtime_vector(**{"2": 1})}},
            "1021": {"pass": {"U": _runtime_vector(**{"2": 99})}},
        }

        result = allocate_from_runtime_data(
            "1300069",
            flow,
            extend,
            experience_table=self.table,
            cross_info=cross_info,
        )

        runtime = result["runtime_input"]
        self.assertTrue(runtime["quality_passed"])
        self.assertEqual(runtime["normalization_mode"], "complete_cycle_scaled_to_10min")
        self.assertEqual(runtime["cycle"]["selected_cycle_count"], 2)
        self.assertEqual(runtime["cycle"]["selected_seconds"], 20)
        self.assertEqual(runtime["normalization_factor"], 30.0)
        self.assertEqual(runtime["flow_selection"]["selected_records"], 1)
        self.assertEqual(result["flow_10min"]["U"][2], 30)
        self.assertEqual(result["times"]["U"], 50)

    def test_partial_boundary_cycle_is_not_treated_as_complete(self):
        cross_info = {
            "1300069": {
                "phase": {"1": "U", "2": "D"},
                "LaneNo": {"U": {"2": "1B"}},
                "Cycle": [[2, 1]],
            }
        }
        # Like the attached sample: it starts in 1 and ends in 1, so 2->1
        # touches the right data boundary and is not a complete cycle.
        extend = _extend("1300069", [1] * 5 + [2] * 5 + [1] * 5)
        flow = {
            "1006": {"pass": {"U": _runtime_vector(**{"2": 3})}},
        }

        result = allocate_from_runtime_data(
            "1300069",
            flow,
            extend,
            experience_table=self.table,
            cross_info=cross_info,
        )

        runtime = result["runtime_input"]
        self.assertFalse(runtime["quality_passed"])
        self.assertEqual(
            runtime["normalization_mode"],
            "partial_window_unscaled_no_complete_cycle",
        )
        self.assertEqual(runtime["normalization_factor"], 1.0)
        self.assertEqual(result["flow_10min"]["U"][2], 3)

    def test_chuli_shuju_new_returns_legacy_vector(self):
        cross_info = {
            "1300069": {
                "phase": {"1": "U"},
                "LaneNo": {"U": {"2": "1B"}},
                "Cycle": [],
            }
        }
        flow = {
            "1000": {"pass": {"U": _runtime_vector(**{"2": 15})}},
        }
        extend = _extend("1300069", [1] * 600)

        schedule = chuli_shuju_new(
            "1300069",
            flow,
            extend,
            experience_table=self.table,
            cross_info=cross_info,
        )

        self.assertEqual(schedule[0], 30)
        self.assertEqual(len(schedule), 10)


if __name__ == "__main__":
    unittest.main()
