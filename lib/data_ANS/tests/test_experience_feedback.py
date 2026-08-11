import unittest

from lib.data_ANS import experience_feedback as FEEDBACK


def _flow(lane, value):
    result = [0] * 10
    result[lane] = value
    return result


class ExperienceFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.cross_info = {
            "1300069": {
                "LaneNo": {"U": {"1": "1A", "2": "1B", "3": "1C"}}
            }
        }
        self.table = {
            "1300069": {
                "U": {"30": _flow(2, 20)},
                "UTL": {"20": _flow(1, 8)},
            }
        }

    def test_only_saturated_clean_executed_observation_is_qualified(self):
        record = {
            "CrossId": "1300069",
            "direction": "U",
            "actual_green_time": 30,
            "observed_flow": _flow(2, 18),
            "quality_gate_passed": True,
            "control_executed": True,
            "downstream_blocked": False,
            "queue_saturated": True,
            "experience_release_id": "experience_test",
        }

        result = FEEDBACK.assess_capacity_observation(
            record,
            self.table,
            self.cross_info,
        )

        self.assertEqual(result["status"], "qualified_capacity_sample")
        self.assertEqual(result["expected_capacity"], 20)
        self.assertEqual(result["observed_flow"], 18)

    def test_demand_limited_and_left_turn_lane_sets_remain_separate(self):
        record = {
            "CrossId": "1300069",
            "direction": "UTL",
            "actual_green_time": 20,
            "observed_flow": _flow(1, 8),
            "quality_gate_passed": True,
            "control_executed": True,
            "downstream_blocked": False,
            "queue_saturated": False,
        }

        result = FEEDBACK.assess_capacity_observation(
            record,
            self.table,
            self.cross_info,
        )

        self.assertEqual(result["lane_indexes"], [1])
        self.assertEqual(result["status"], "demand_limited")

    def test_feedback_summary_keeps_only_qualified_samples(self):
        records = [
            {
                "CrossId": "1300069",
                "direction": "U",
                "actual_green_time": 30,
                "observed_flow": _flow(2, 20),
                "quality_gate_passed": True,
                "control_executed": True,
                "downstream_blocked": False,
                "queue_saturated": True,
            },
            {
                "CrossId": "1300069",
                "direction": "U",
                "actual_green_time": 30,
                "observed_flow": _flow(2, 5),
                "quality_gate_passed": True,
                "control_executed": True,
                "downstream_blocked": False,
                "queue_saturated": False,
            },
        ]

        report = FEEDBACK.evaluate_feedback_records(
            records,
            self.table,
            self.cross_info,
        )

        self.assertEqual(report["summary"]["qualified_capacity_sample"], 1)
        self.assertEqual(report["summary"]["demand_limited"], 1)
        self.assertEqual(
            report["qualified_points"]["1300069/U/30"]["qualified_samples"],
            1,
        )

    def test_unknown_downstream_state_does_not_enter_the_pool(self):
        record = {
            "CrossId": "1300069",
            "direction": "U",
            "actual_green_time": 30,
            "observed_flow": _flow(2, 20),
            "quality_gate_passed": True,
            "control_executed": True,
            "downstream_blocked": None,
            "queue_saturated": True,
        }

        result = FEEDBACK.assess_capacity_observation(
            record,
            self.table,
            self.cross_info,
        )

        self.assertEqual(result["status"], "downstream_state_unknown")

    def test_capacity_lane_indexes_mask_non_candidate_lanes(self):
        record = {
            "CrossId": "1300069",
            "direction": "U",
            "actual_green_time": 30,
            "observed_flow": _flow(2, 20),
            "capacity_lane_indexes": [2],
            "quality_gate_passed": True,
            "control_executed": True,
            "downstream_blocked": False,
            "saturation_confirmed": True,
        }

        result = FEEDBACK.assess_capacity_observation(
            record,
            self.table,
            self.cross_info,
        )

        self.assertEqual(result["status"], "qualified_capacity_sample")
        self.assertEqual(result["lane_indexes"], [2])
        self.assertEqual(result["observed_lane_flow"], _flow(2, 20))

    def test_uncontrolled_right_turn_lane_cannot_reenter_feedback_pool(self):
        record = {
            "CrossId": "1300069",
            "direction": "U",
            "actual_green_time": 30,
            "observed_flow": _flow(3, 20),
            "capacity_lane_indexes": [3],
            "quality_gate_passed": True,
            "control_executed": True,
            "downstream_blocked": False,
            "saturation_confirmed": True,
        }

        result = FEEDBACK.assess_capacity_observation(
            record,
            self.table,
            self.cross_info,
        )

        self.assertEqual(result["status"], "invalid_capacity_lane_indexes")
        self.assertEqual(result["excluded_uncontrolled_lane_indexes"], [3])

    def test_only_qualified_feedback_reenters_candidate_audit(self):
        records = [
            {
                "CrossId": "1300069",
                "direction": "U",
                "actual_green_time": 30,
                "observed_flow": _flow(2, 20),
                "quality_gate_passed": True,
                "control_executed": True,
                "downstream_blocked": False,
                "queue_saturated": True,
                "source_date": "2026-07-31",
                "source_window_start": 1785470400,
                "experience_release_id": "experience_test",
            },
            {
                "CrossId": "1300069",
                "direction": "U",
                "actual_green_time": 30,
                "observed_flow": _flow(2, 5),
                "quality_gate_passed": True,
                "control_executed": True,
                "downstream_blocked": False,
                "queue_saturated": False,
                "source_date": "2026-07-31",
                "source_window_start": 1785471000,
            },
        ]
        report = FEEDBACK.evaluate_feedback_records(
            records,
            self.table,
            self.cross_info,
        )

        candidates, stats = FEEDBACK.build_qualified_candidate_samples(
            report["assessments"]
        )
        audit = FEEDBACK.audit_candidate_samples(candidates)

        samples = candidates["roads"]["1300069"]["directions"]["U"]["30"]
        self.assertEqual(stats["qualified_samples"], 1)
        self.assertEqual(stats["excluded_non_capacity_observation"], 1)
        self.assertEqual(samples[0]["flow"], _flow(2, 20))
        self.assertEqual(
            audit["roads"]["1300069"]["directions"]["U"]["30"]["sample_count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
