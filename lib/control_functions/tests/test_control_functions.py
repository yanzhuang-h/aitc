import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json

from lib.control_functions import (
    get_intersection_processing_types,
    get_timetable_plan,
    process_flow_intersections,
    process_internet_intersections,
    process_mixed_intersections,
    validate_control_plan,
)


class ControlFunctionTests(unittest.TestCase):
    def test_plan_contract(self):
        plan, warnings = validate_control_plan([1.9] * 8 + [0, 2])
        self.assertEqual(plan, [1] * 8 + [0, 2])
        self.assertEqual(warnings, [])

    def test_plan_contract_rejects_wrong_length(self):
        with self.assertRaises(ValueError):
            validate_control_plan([1, 2])

    def test_overlapping_road_types_are_preserved(self):
        self.assertEqual(
            get_intersection_processing_types("1300069"),
            ("internet", "mixed"),
        )
        self.assertEqual(
            get_intersection_processing_types("1700086"),
            ("internet", "flow"),
        )

    @patch("lib.control_functions.global_control.coordinate_internet_roads")
    def test_internet_wrapper_forwards_legacy_maps(self, coordinate_mock):
        coordinate_mock.return_value = {"1": [1] * 10}
        result = process_internet_intersections(
            {"1": [0] * 10}, {"1": {}}, {"rid": {}}, {}, {"1": {}}
        )
        self.assertEqual(result, {"1": [1] * 10})
        coordinate_mock.assert_called_once()

    @patch("lib.control_functions.global_control.coordinate_mixed_roads")
    def test_mixed_wrapper_uses_mixed_processor(self, coordinate_mock):
        coordinate_mock.return_value = {}
        process_mixed_intersections({}, {}, {}, {})
        coordinate_mock.assert_called_once()

    @patch("lib.control_functions.global_control.coordinate_flow_roads")
    def test_flow_wrapper_uses_flow_processor(self, coordinate_mock):
        coordinate_mock.return_value = {}
        process_flow_intersections({}, {}, {}, {})
        coordinate_mock.assert_called_once()

    def test_timetable_plan_uses_requested_local_hour(self):
        timetable = {str(hour): [hour] + [0] * 9 for hour in range(24)}
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Time_schedule_123.json"
            path.write_text(json.dumps(timetable), encoding="utf-8")
            result = get_timetable_plan(
                "123", datetime(2026, 8, 10, 7, 30), schedule_dir=temp_dir
            )
        self.assertTrue(result.success)
        self.assertEqual(result.plan[0], 7)
        self.assertEqual(result.source, "time_schedule_workday")

    def test_runtime_timetable_has_priority(self):
        timetable = {str(hour): [hour + 1] + [0] * 9 for hour in range(24)}
        result = get_timetable_plan(
            "123",
            datetime(2026, 8, 10, 8),
            runtime_schedules={"123": timetable},
        )
        self.assertTrue(result.success)
        self.assertEqual(result.plan[0], 9)
        self.assertEqual(result.source, "time_schedule_runtime")

    def test_missing_timetable_returns_failure_result(self):
        with TemporaryDirectory() as temp_dir:
            result = get_timetable_plan(
                "missing", datetime(2026, 8, 10, 8), schedule_dir=temp_dir
            )
        self.assertFalse(result.success)
        self.assertEqual(result.plan, [0] * 10)
        self.assertIn("FileNotFoundError", result.error)


if __name__ == "__main__":
    unittest.main()
