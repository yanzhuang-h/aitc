import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from lib.data_ANS import experience_runtime as RUNTIME
from lib.data_ANS.experience_runtime import (
    ExperiencePoolScheduler,
    run_experience_pool_day,
)


class ExperienceRuntimeTests(unittest.TestCase):
    def test_default_collection_and_update_scopes_are_independent(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            update_roads = RUNTIME._configured_update_roads()
            collection_roads = RUNTIME._configured_collection_roads()

        self.assertTrue({"2272", "2620"}.issubset(collection_roads))
        self.assertTrue({"2272", "2620"}.issubset(update_roads))
        self.assertTrue(update_roads.issubset(set(collection_roads)))

    def test_scheduler_uses_t_minus_two_without_startup_catchup(self):
        self.assertEqual(
            ExperiencePoolScheduler.source_date_for_run(
                dt.date(2026, 7, 26)
            ),
            dt.date(2026, 7, 24),
        )

    def test_seconds_until_next_daily_noon(self):
        timezone = dt.timezone(dt.timedelta(hours=8))
        now = dt.datetime(2026, 7, 25, 11, 59, 30, tzinfo=timezone)

        self.assertEqual(
            ExperiencePoolScheduler.seconds_until_next_daily_run(now),
            30,
        )

        after_noon = dt.datetime(2026, 7, 25, 12, 0, 30, tzinfo=timezone)
        self.assertEqual(
            ExperiencePoolScheduler.seconds_until_next_daily_run(after_noon),
            86370,
        )

    def test_initial_test_run_is_opt_in_and_can_use_five_minutes(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                ExperiencePoolScheduler.initial_delay_seconds(),
                0,
            )
        with mock.patch.dict(
            os.environ,
            {"AITC_EXPERIENCE_POOL_INITIAL_DELAY_SECONDS": "300"},
            clear=True,
        ):
            self.assertEqual(
                ExperiencePoolScheduler.initial_delay_seconds(),
                300,
            )

    def test_scheduler_can_run_an_explicit_source_date_for_testing(self):
        scheduler = ExperiencePoolScheduler()
        with mock.patch.object(
            RUNTIME,
            "run_experience_pool_day",
            return_value={"status": "completed"},
        ) as run_day:
            scheduler.run_for_date(source_date="2026-07-17")

        run_day.assert_called_once_with(dt.date(2026, 7, 17), release_settings=None)

    def test_missing_source_files_are_skipped_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ,
                {"AITC_EXPERIENCE_POOL_STATE_DIR": directory},
            ):
                first = run_experience_pool_day("2099-01-01")
                second = run_experience_pool_day("2099-01-01")

            self.assertEqual(first, second)
            self.assertEqual(first["status"], "skipped_missing_source_data")
            manifest = Path(directory) / "runs" / "2099-01-01.json"
            self.assertTrue(manifest.exists())
            self.assertFalse(first["pool_committed"])
            self.assertFalse(first["table_updated"])

    def _run_raw_feedback_day(self, initial_table, minimum_samples=1):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs_data"
            flow_dir = logs / "flow"
            extend_dir = logs / "extend"
            flow_dir.mkdir(parents=True)
            extend_dir.mkdir(parents=True)
            state_dir = root / "pool_state"
            runtime_path = root / "wwx.json"
            cross_info_path = root / "cross_info.json"
            versions_dir = root / "versions"
            source_date = dt.date(2026, 7, 24)
            start_time, _ = RUNTIME._source_day_bounds(source_date)

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
            if initial_table is not None:
                runtime_path.write_text(
                    json.dumps(initial_table),
                    encoding="utf-8",
                )
            cross_info_path.write_text(
                json.dumps(cross_info),
                encoding="utf-8",
            )

            extend_rows = []
            flow_rows = []
            for offset in range(600):
                stage = "1" if offset % 20 < 10 else "2"
                extend_rows.append({
                    "CrossId": "1",
                    "time": (start_time + offset) * 1000,
                    "curStageNo": stage,
                })
                stage_offset = offset % 20
                if stage_offset in (4, 8):
                    detector = "10" if stage == "1" else "11"
                    flow_rows.append({
                        "jtll_ddbh": detector,
                        "ts": str((start_time + offset) * 1000),
                        "ycsb_cdbh": "1",
                        "ycsb_xsfx": "1B",
                    })

            (flow_dir / "2026-07-24_flow.txt").write_text(
                "\n".join(json.dumps(row) for row in flow_rows),
                encoding="utf-8",
            )
            (extend_dir / "2026-07-24_extend.txt").write_text(
                "\n".join(json.dumps(row) for row in extend_rows),
                encoding="utf-8",
            )
            environment = {
                "AITC_EXPERIENCE_POOL_STATE_DIR": str(state_dir),
                "AITC_EXPERIENCE_POOL_ARTIFACT_DIR": str(root / "artifacts"),
                "AITC_EXPERIENCE_RUNTIME_TABLE": str(runtime_path),
                "AITC_EXPERIENCE_CROSS_INFO": str(cross_info_path),
                "AITC_EXPERIENCE_VERSIONS_DIR": str(versions_dir),
                "AITC_EXPERIENCE_MANIFEST": str(
                    versions_dir / "active_manifest.json"
                ),
                "AITC_EXPERIENCE_POOL_ROADS": "1",
                "AITC_EXPERIENCE_TABLE_UPDATE_ROADS": "1",
                "AITC_EXPERIENCE_POOL_MIN_SAMPLES": str(minimum_samples),
            }
            with mock.patch.object(RUNTIME, "LOGS_DIR", logs), mock.patch.dict(
                os.environ,
                environment,
            ):
                report = run_experience_pool_day(source_date)

            updated = (
                json.loads(runtime_path.read_text(encoding="utf-8"))
                if runtime_path.exists() else None
            )
            return report, updated, (versions_dir / "active_manifest.json").exists()

    def test_daily_job_runs_raw_data_to_versioned_table_update(self):
        initial = {
            "1": {
                "U": {"10": [0, 10] + [0] * 8},
                "D": {"10": [0, 10] + [0] * 8},
            }
        }
        report, updated, activated = self._run_raw_feedback_day(initial)
        self.assertEqual(report["status"], "completed_table_updated")
        self.assertTrue(report["pool_committed"])
        self.assertTrue(report["table_updated"])
        self.assertGreater(report["candidate_count"], 0)
        self.assertEqual(report["selection_method"], "densest_cluster_median")
        self.assertEqual(report["cluster_fraction"], 0.5)
        self.assertNotEqual(updated, initial)
        self.assertTrue(activated)

    def test_first_start_can_learn_from_empty_or_missing_table(self):
        for initial in ({}, None):
            with self.subTest(initial=initial):
                report, updated, activated = self._run_raw_feedback_day(initial)
                self.assertEqual(report["status"], "completed_table_updated")
                self.assertTrue(report["pool_committed"])
                self.assertTrue(report["table_updated"])
                self.assertGreater(report["candidate_count"], 0)
                self.assertTrue(updated["1"]["U"])
                # 未达到候选条件的方向不补造经验值，继续沿用原有回退。
                self.assertNotIn("D", updated["1"])
                self.assertTrue(activated)

    def test_bootstrap_preserves_sample_threshold_and_does_not_publish_empty_table(self):
        report, updated, activated = self._run_raw_feedback_day({}, minimum_samples=30)
        self.assertEqual(report["status"], "completed_pool_updated_no_table_change")
        self.assertGreater(report["candidate_count"], 0)
        self.assertTrue(report["pool_committed"])
        self.assertFalse(report["table_updated"])
        self.assertEqual(updated, {})
        self.assertFalse(activated)

    def test_invalid_nonempty_or_wrong_type_table_still_blocks_learning(self):
        for initial in ({"1": {}}, [], {"1": {"U": {"10": [-1] * 10}}}):
            with self.subTest(initial=initial), mock.patch.object(
                RUNTIME, "normalize_raw_feedback"
            ) as normalize:
                report, updated, activated = self._run_raw_feedback_day(initial)
            self.assertEqual(report["status"], "skipped_invalid_active_table")
            self.assertFalse(report["pool_committed"])
            self.assertFalse(report["table_updated"])
            self.assertEqual(updated, initial)
            self.assertFalse(activated)
            normalize.assert_not_called()



if __name__ == "__main__":
    unittest.main()
