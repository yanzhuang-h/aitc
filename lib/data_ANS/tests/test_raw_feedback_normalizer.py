import json
import tempfile
import unittest
from pathlib import Path

from lib.data_ANS.raw_feedback_normalizer import (
    _complete_flow_window_green_runs,
    _flow_discharge_evidence,
    _movement_lane_configuration,
    build_near_capacity_candidate_samples,
    normalize_raw_feedback,
)


class RawFeedbackNormalizerTests(unittest.TestCase):
    def test_uncontrolled_right_turn_lane_is_not_a_capacity_lane(self):
        cross_config = {
            "LaneNo": {
                "U": {"1": "1A", "2": "1B", "3": "1C", "4": "2B"}
            }
        }

        base_lanes, excluded = _movement_lane_configuration(cross_config, "U")
        left_lanes, left_excluded = _movement_lane_configuration(
            cross_config,
            "UTL",
        )

        self.assertEqual(base_lanes, {2, 4})
        self.assertEqual(excluded, {3: "1C"})
        self.assertEqual(left_lanes, {1})
        self.assertEqual(left_excluded, {})

    def test_green_runs_outside_fixed_flow_window_are_excluded(self):
        runs = [
            {"start": 90, "end": 106},
            {"start": 100, "end": 106},
            {"start": 104, "end": 120},
        ]

        result = _complete_flow_window_green_runs(runs, 100, 110)

        self.assertEqual(result, [{"start": 100, "end": 106}])

    def test_three_vehicles_in_seven_seconds_is_not_an_empty_release(self):
        evidence = _flow_discharge_evidence(
            {"U": {1: [100, 102, 104, 120, 122, 124]}},
            "U",
            {1},
            [{"start": 100, "end": 106}, {"start": 120, "end": 126}],
        )

        self.assertEqual(
            evidence["saturation_state"],
            "near_capacity_all_lanes",
        )
        self.assertIsNone(evidence["saturation_confirmed"])
        self.assertEqual(evidence["near_capacity_lane_indexes"], [1])
        self.assertEqual(evidence["strict_likely_saturated_lane_indexes"], [1])

    def test_one_vehicle_in_the_final_seven_seconds_is_an_empty_release(self):
        evidence = _flow_discharge_evidence(
            {"U": {1: [100, 120]}},
            "U",
            {1},
            [{"start": 100, "end": 106}, {"start": 120, "end": 126}],
        )

        self.assertEqual(
            evidence["saturation_state"],
            "near_capacity_all_lanes",
        )
        self.assertIsNone(evidence["saturation_confirmed"])
        self.assertEqual(evidence["near_capacity_lane_indexes"], [1])

    def test_candidate_export_records_only_near_capacity_lanes(self):
        observations = [{
            "CrossId": "1",
            "direction": "U",
            "actual_green_time": 30,
            "source_date": "2026-07-01",
            "source_window_start": 100,
            "quality_gate_passed": True,
            "capacity_lane_indexes": [2],
            "candidate_observed_flow": [0, 0, 8] + [0] * 7,
            "flow_window_green_run_count": 3,
            "flow_discharge_evidence": {
                "near_capacity_max_clearance_seconds": 10,
                "strict_likely_saturated_lane_indexes": [],
                "excluded_uncontrolled_lane_indexes": [3],
            },
        }]

        candidates, stats = build_near_capacity_candidate_samples(observations)
        sample = candidates["roads"]["1"]["directions"]["U"]["30"][0]

        self.assertEqual(stats["accepted_samples"], 1)
        self.assertEqual(sample["flow"], [0, 0, 8] + [0] * 7)
        self.assertEqual(sample["metadata"]["capacity_lane_indexes"], [2])
        self.assertEqual(
            sample["metadata"]["excluded_uncontrolled_lane_indexes"],
            [3],
        )

    def test_normalizes_only_complete_windows_with_pre_green_queue_evidence(self):
        cross_info = {
            "1": {
                "jtll_ddbh": {"10": "U", "11": "D"},
                "LaneNo": {
                    "U": {"1": "1B"},
                    "D": {"1": "1B"},
                },
                "phase": {"1": "U", "2": "D"},
                "Cycle": [[1, 2]],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_time = 1_699_999_800
            flow_path = root / "flow.txt"
            extend_path = root / "extend.txt"
            queue_path = root / "queue.txt"

            flow_rows = [
                {
                    "jtll_ddbh": "10",
                    "ts": str((base_time + index) * 1000),
                    "ycsb_cdbh": "1",
                    "ycsb_xsfx": "1B",
                }
                for index in range(12)
            ]
            flow_rows.extend(
                {
                    "jtll_ddbh": "11",
                    "ts": str((base_time + 20 + index) * 1000),
                    "ycsb_cdbh": "1",
                    "ycsb_xsfx": "1B",
                }
                for index in range(8)
            )
            extend_rows = []
            queue_rows = []
            for timestamp in range(base_time, base_time + 600):
                stage = "1" if ((timestamp - base_time) % 20) < 10 else "2"
                extend_rows.append({
                    "CrossId": "1",
                    "time": timestamp * 1000,
                    "curStageNo": stage,
                })
                for detector in ("10", "11"):
                    queue_rows.append({
                        "jtll_ddbh": detector,
                        "start_time": str(timestamp * 1000),
                        "car_nums": [{"ycsb_cdbh": "1", "queue": 2}],
                    })

            flow_path.write_text(
                "\n".join(json.dumps(row) for row in flow_rows),
                encoding="utf-8",
            )
            extend_path.write_text(
                "\n".join(json.dumps(row) for row in extend_rows),
                encoding="utf-8",
            )
            queue_path.write_text(
                "\n".join(json.dumps(row) for row in queue_rows),
                encoding="utf-8",
            )

            observations, report = normalize_raw_feedback(
                str(flow_path),
                str(extend_path),
                str(queue_path),
                cross_info,
                "2026-07-01",
                base_time,
                base_time + 599,
                target_cross_ids=["1"],
            )

        self.assertEqual(report["observation_count"], 2)
        by_direction = {row["direction"]: row for row in observations}
        self.assertEqual(set(by_direction), {"U", "D"})
        self.assertEqual(by_direction["U"]["actual_green_time"], 10)
        self.assertEqual(by_direction["U"]["observed_flow"][1], 12)
        self.assertEqual(by_direction["D"]["observed_flow"][1], 8)
        self.assertFalse(by_direction["U"]["saturation_confirmed"])
        self.assertEqual(
            by_direction["U"]["saturation_state"],
            "not_near_capacity_release",
        )
        self.assertEqual(by_direction["U"]["control_executed"], None)
        self.assertEqual(by_direction["U"]["downstream_blocked"], None)


if __name__ == "__main__":
    unittest.main()
