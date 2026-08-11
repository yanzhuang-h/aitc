import json
import tempfile
import unittest
from pathlib import Path

from lib.data_ANS.experience_pool_maintenance import (
    prune_experience_pool_data,
    prune_experience_pool_file,
    subtract_calendar_months,
)


def _record(date, window_start):
    return {
        "flow": 20,
        "date": date,
        "window_start": window_start,
        "source_id": f"{date}:{window_start}",
        "metadata": {},
    }


def _pool(lane_records):
    return {
        "version": 2,
        "state": {"processed_source_dates": ["2026-01-01"]},
        "roads": {
            "1": {
                "U": {
                    "60": lane_records,
                }
            }
        },
    }


class ExperiencePoolMaintenanceTests(unittest.TestCase):
    def test_calendar_month_subtraction_clamps_month_end(self):
        self.assertEqual(
            subtract_calendar_months("2026-05-31", 3).isoformat(),
            "2026-02-28",
        )

    def test_prunes_oldest_expired_records_but_stops_at_one_hundred(self):
        records = [
            _record("2026-01-01", index)
            for index in range(15)
        ] + [
            _record("2026-07-01", 100 + index)
            for index in range(95)
        ]

        result, report = prune_experience_pool_data(
            _pool({"1": records}),
            as_of_date="2026-08-01",
        )

        retained = result["roads"]["1"]["U"]["60"]["1"]
        self.assertEqual(len(retained), 100)
        self.assertEqual(
            [record["window_start"] for record in retained[:5]],
            [10, 11, 12, 13, 14],
        )
        cell = report["lane_cells"]["1/U/60/1"]
        self.assertEqual(cell["records_removed"], 10)
        self.assertEqual(cell["expired_records_remaining"], 5)
        self.assertEqual(cell["decision"], "pruned_until_minimum_record_count")

    def test_does_not_prune_a_lane_cell_with_only_one_hundred_records(self):
        records = [
            _record("2026-01-01", index)
            for index in range(20)
        ] + [
            _record("2026-07-01", 100 + index)
            for index in range(80)
        ]

        result, report = prune_experience_pool_data(
            _pool({"1": records}),
            as_of_date="2026-08-01",
        )

        retained = result["roads"]["1"]["U"]["60"]["1"]
        self.assertEqual(len(retained), 100)
        cell = report["lane_cells"]["1/U/60/1"]
        self.assertEqual(cell["records_removed"], 0)
        self.assertEqual(cell["decision"], "protected_minimum_record_count")

    def test_removes_all_expired_records_when_more_than_one_hundred_remain(self):
        records = [
            _record("2026-01-01", index)
            for index in range(5)
        ] + [
            _record("2026-07-01", 100 + index)
            for index in range(125)
        ]

        result, report = prune_experience_pool_data(
            _pool({"1": records}),
            as_of_date="2026-08-01",
        )

        retained = result["roads"]["1"]["U"]["60"]["1"]
        self.assertEqual(len(retained), 125)
        cell = report["lane_cells"]["1/U/60/1"]
        self.assertEqual(cell["records_removed"], 5)
        self.assertEqual(cell["expired_records_remaining"], 0)
        self.assertEqual(cell["decision"], "all_expired_records_pruned")

    def test_file_command_is_dry_run_until_apply_is_true(self):
        records = [
            _record("2026-01-01", index)
            for index in range(10)
        ] + [
            _record("2026-07-01", 100 + index)
            for index in range(95)
        ]
        with tempfile.TemporaryDirectory() as directory:
            pool_path = Path(directory) / "pool.json"
            pool_path.write_text(json.dumps(_pool({"1": records})), encoding="utf-8")

            _, dry_report = prune_experience_pool_file(
                str(pool_path),
                as_of_date="2026-08-01",
            )
            unchanged = json.loads(pool_path.read_text(encoding="utf-8"))
            self.assertEqual(len(unchanged["roads"]["1"]["U"]["60"]["1"]), 105)
            self.assertFalse(dry_report["applied"])

            _, applied_report = prune_experience_pool_file(
                str(pool_path),
                as_of_date="2026-08-01",
                apply=True,
            )
            changed = json.loads(pool_path.read_text(encoding="utf-8"))
            self.assertEqual(len(changed["roads"]["1"]["U"]["60"]["1"]), 100)
            self.assertTrue(applied_report["applied"])


if __name__ == "__main__":
    unittest.main()
