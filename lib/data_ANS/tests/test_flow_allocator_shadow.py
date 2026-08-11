from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from lib.data_ANS import flow_allocator_shadow as SHADOW
from lib.data_ANS.flow_allocator_shadow import (
    record_shadow_comparison,
    select_pilot_schedule,
)


def _vector(**values):
    result = [0] * 10
    for lane, value in values.items():
        result[int(lane)] = value
    return result


class FlowAllocatorShadowTests(unittest.TestCase):
    def setUp(self):
        self.cross_info = {
            "1300069": {
                "phase": {"3": "LR"},
                "LaneNo": {"U": {"1": "1A", "2": "1B"}},
                "Cycle": [],
            }
        }
        self.experience_table = {
            "1300069": {
                "U": {"30": _vector(**{"2": 20})},
                "UTL": {"20": _vector(**{"1": 10})},
            }
        }
        self.flow = {
            "1000": {
                "pass": {"U": [0, 4, 5, 0, 0, 0, 0]},
            }
        }
        self.extend = {
            float(timestamp): [{
                "CrossId": "1300069",
                "curStageNo": "3",
            }]
            for timestamp in range(1000, 1600)
        }
        self.observed_at = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)

    def test_records_new_result_without_mutating_legacy_schedule(self):
        old_schedule = [41, 42, 43, 44, 21, 22, 23, 24, 0, 0]
        expected_old_schedule = list(old_schedule)
        with tempfile.TemporaryDirectory() as directory:
            record = record_shadow_comparison(
                "1300069",
                old_schedule,
                self.flow,
                self.extend,
                experience_table=self.experience_table,
                cross_info=self.cross_info,
                log_directory=directory,
                observed_at=self.observed_at,
            )

            self.assertEqual(old_schedule, expected_old_schedule)
            self.assertEqual(record["status"], "ok")
            self.assertEqual(record["old_schedule"], expected_old_schedule)
            self.assertEqual(record["selected_schedule"], expected_old_schedule)
            self.assertEqual(record["selected_schedule_source"], "legacy")
            self.assertGreater(record["new_schedule"][0], 0)
            self.assertGreater(record["new_schedule"][4], 0)
            self.assertEqual(record["positive_flow_zero_directions"], [])
            self.assertEqual(record["flow_directions"], ["U", "UTL"])
            self.assertEqual(record["extend_directions"], ["L", "R"])

            log_path = Path(directory) / "flow_time_allocator_2026-07-31.jsonl"
            rows = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])["status"], "ok")

    def test_allocator_error_is_logged_and_not_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertLogs("FlowAllocatorShadow", level="ERROR"):
                record = record_shadow_comparison(
                    "1300069",
                    [1] * 10,
                    self.flow,
                    self.extend,
                    experience_table=self.experience_table,
                    cross_info={},
                    log_directory=directory,
                    observed_at=self.observed_at,
                    runtime_mode="new",
                )

            self.assertEqual(record["status"], "error")
            self.assertEqual(record["error_type"], "KeyError")
            self.assertEqual(record["selected_schedule"], [1] * 10)
            self.assertEqual(record["selected_schedule_source"], "legacy")
            self.assertEqual(
                record["selection_fallback_reason"],
                "new_evaluation_error",
            )
            log_path = Path(directory) / "flow_time_allocator_2026-07-31.jsonl"
            self.assertEqual(
                json.loads(log_path.read_text(encoding="utf-8"))["status"],
                "error",
            )

    def test_disabled_shadow_performs_no_work(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ,
                {"AITC_FLOW_ALLOCATOR_SHADOW_ENABLED": "0"},
            ):
                record = record_shadow_comparison(
                    "1300069",
                    [1] * 10,
                    self.flow,
                    self.extend,
                    experience_table=self.experience_table,
                    cross_info=self.cross_info,
                    log_directory=directory,
                    observed_at=self.observed_at,
                )

            self.assertIsNone(record)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_all_four_configured_roads_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            records = []
            for road_id in ("1300068", "1300070", "1700125"):
                cross_info = {
                    road_id: self.cross_info["1300069"],
                }
                experience_table = {
                    road_id: self.experience_table["1300069"],
                }
                extend = {
                    timestamp: [{
                        "CrossId": road_id,
                        "curStageNo": "3",
                    }]
                    for timestamp in range(1000, 1600)
                }
                records.append(record_shadow_comparison(
                    road_id,
                    [1] * 10,
                    self.flow,
                    extend,
                    experience_table=experience_table,
                    cross_info=cross_info,
                    log_directory=directory,
                    observed_at=self.observed_at,
                ))

            self.assertEqual(
                [record["road_id"] for record in records],
                ["1300068", "1300070", "1700125"],
            )
            self.assertTrue(all(record["status"] == "ok" for record in records))
            log_path = Path(directory) / "flow_time_allocator_2026-07-31.jsonl"
            rows = [
                json.loads(row)
                for row in log_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [row["road_id"] for row in rows],
                ["1300068", "1300070", "1700125"],
            )

    def test_non_target_road_does_not_create_a_log(self):
        with tempfile.TemporaryDirectory() as directory:
            record = record_shadow_comparison(
                "1300086",
                [1] * 10,
                self.flow,
                self.extend,
                experience_table=self.experience_table,
                cross_info=self.cross_info,
                log_directory=directory,
                observed_at=self.observed_at,
            )

            self.assertIsNone(record)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_pilot_selector_switches_legacy_shadow_and_new(self):
        legacy = [1] * 10

        def fake_record(road_id, old_schedule, flow, extend, runtime_mode):
            selected = [9] * 10 if runtime_mode == "new" else list(old_schedule)
            return {"selected_schedule": selected}

        with mock.patch.object(
            SHADOW,
            "record_shadow_comparison",
            side_effect=fake_record,
        ) as recorder:
            with mock.patch.dict(
                os.environ,
                {"AITC_FLOW_ALLOCATOR_PILOT_MODE": "legacy"},
            ):
                self.assertEqual(
                    select_pilot_schedule(
                        "1300069",
                        legacy,
                        self.flow,
                        self.extend,
                    ),
                    legacy,
                )
            recorder.assert_not_called()

            with mock.patch.dict(
                os.environ,
                {"AITC_FLOW_ALLOCATOR_PILOT_MODE": "shadow"},
            ):
                self.assertEqual(
                    select_pilot_schedule(
                        "1300069",
                        legacy,
                        self.flow,
                        self.extend,
                    ),
                    legacy,
                )

            with mock.patch.dict(
                os.environ,
                {"AITC_FLOW_ALLOCATOR_PILOT_MODE": "new"},
            ):
                self.assertEqual(
                    select_pilot_schedule(
                        "1300069",
                        legacy,
                        self.flow,
                        self.extend,
                    ),
                    [9] * 10,
                )

    def test_non_pilot_selector_always_returns_legacy(self):
        legacy = [3] * 10
        with mock.patch.object(SHADOW, "record_shadow_comparison") as recorder:
            selected = select_pilot_schedule(
                "1300086",
                legacy,
                self.flow,
                self.extend,
            )

        self.assertEqual(selected, legacy)
        recorder.assert_not_called()

    def test_new_mode_rejects_an_all_zero_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            record = record_shadow_comparison(
                "1300069",
                [30] * 8 + [0, 0],
                {},
                {},
                experience_table=self.experience_table,
                cross_info=self.cross_info,
                log_directory=directory,
                observed_at=self.observed_at,
                runtime_mode="new",
            )

        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["selected_schedule_source"], "legacy")
        self.assertEqual(
            record["selection_fallback_reason"],
            "new_schedule_all_directions_zero",
        )

    def test_new_mode_can_select_nonzero_result_when_quality_is_false(self):
        short_extend = {
            float(timestamp): [{
                "CrossId": "1300069",
                "curStageNo": "3",
            }]
            for timestamp in range(1000, 1010)
        }
        with tempfile.TemporaryDirectory() as directory:
            record = record_shadow_comparison(
                "1300069",
                [30] * 8 + [0, 0],
                self.flow,
                short_extend,
                experience_table=self.experience_table,
                cross_info=self.cross_info,
                log_directory=directory,
                observed_at=self.observed_at,
                runtime_mode="new",
            )

        self.assertEqual(record["status"], "ok")
        self.assertFalse(record["quality_passed"])
        self.assertEqual(record["selected_schedule_source"], "new")


if __name__ == "__main__":
    unittest.main()
