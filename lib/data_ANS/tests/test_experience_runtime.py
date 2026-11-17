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
        from lib.road_groups import TONGZHOU_19
        self.assertTrue(TONGZHOU_19.issubset(update_roads))

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

    def _run_raw_feedback_day(self, initial_table, minimum_samples=1, road_id="1",
                              resume_after_skip=None, repeat_completed=False, interrupt_publication=False):
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
                road_id: {
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
                    "CrossId": road_id,
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
                "AITC_EXPERIENCE_POOL_ROADS": road_id,
                "AITC_EXPERIENCE_TABLE_UPDATE_ROADS": road_id,
                "AITC_EXPERIENCE_POOL_MIN_SAMPLES": str(minimum_samples),
            }
            with mock.patch.object(RUNTIME, "LOGS_DIR", logs), mock.patch.dict(
                os.environ,
                environment,
            ):
                if resume_after_skip:
                    if resume_after_skip == "missing_source":
                        broken_path = extend_dir / "2026-07-24_extend.txt"
                        original = broken_path.read_bytes()
                        broken_path.unlink()
                    elif resume_after_skip == "invalid_table":
                        broken_path = runtime_path
                        original = broken_path.read_bytes()
                        broken_path.write_text('{"1": {}}', encoding="utf-8")
                    else:
                        broken_path = cross_info_path
                        original = broken_path.read_bytes()
                        broken_path.write_text("{}", encoding="utf-8")
                    skipped = run_experience_pool_day(source_date)
                    expected_status = {
                        "missing_source": "skipped_missing_source_data",
                        "invalid_table": "skipped_invalid_active_table",
                        "missing_cross": "skipped_missing_cross_configuration",
                    }[resume_after_skip]
                    self.assertEqual(skipped["status"], expected_status)
                    broken_path.write_bytes(original)
                if interrupt_publication:
                    from lib.data_ANS import experience_release as release
                    original_write = release._write_json_atomic
                    def fail_manifest(path, data):
                        if str(path) == str(versions_dir / "active_manifest.json"):
                            raise OSError("interrupted after runtime table")
                        return original_write(path, data)
                    with mock.patch.object(release, "_write_json_atomic", side_effect=fail_manifest):
                        with self.assertRaisesRegex(OSError, "interrupted"):
                            run_experience_pool_day(source_date)
                    pool_path = state_dir / "online_experience_samples.json"
                    interrupted = json.loads(pool_path.read_text())
                    self.assertTrue(interrupted["state"]["pending_publication"])
                    table_before_resume = runtime_path.read_bytes()
                report = run_experience_pool_day(source_date)
                if interrupt_publication:
                    resumed = json.loads(pool_path.read_text())
                    self.assertFalse(resumed["state"]["pending_publication"])
                    self.assertEqual(resumed["roads"], interrupted["roads"])
                    self.assertEqual(runtime_path.read_bytes(), table_before_resume)
                    manifest = json.loads((versions_dir / "active_manifest.json").read_text())
                    self.assertEqual(manifest["active_sha256"], release._canonical_hash(
                        json.loads(runtime_path.read_text())))
                if repeat_completed:
                    table_bytes = runtime_path.read_bytes()
                    pool_path = state_dir / "online_experience_samples.json"
                    pool_bytes = pool_path.read_bytes()
                    self.assertEqual(run_experience_pool_day(source_date), report)
                    self.assertEqual(runtime_path.read_bytes(), table_bytes)
                    self.assertEqual(pool_path.read_bytes(), pool_bytes)

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

    def test_19_and_49_existing_roads_can_add_qualified_direction_and_time_point(self):
        for road in ("1700240", "1700125", "1700448"):
            for initial in [
                {road: {"D": {"10": [0, 10] + [0] * 8}}},
                {road: {"U": {"9": [0, 10] + [0] * 8}}},
            ]:
                with self.subTest(road=road, initial=initial):
                    report, updated, activated = self._run_raw_feedback_day(
                        initial, road_id=road,
                    )
                    self.assertEqual(report["status"], "completed_table_updated")
                    self.assertTrue(activated)
                    self.assertGreater(updated[road]["U"]["10"][1], 0)
                    for direction, points in initial[road].items():
                        for green, value in points.items():
                            self.assertEqual(updated[road][direction][green], value)
                    self.assertEqual(report["pool_summary"]["blend"]["new_experience_points_seeded"], 1)

    def test_existing_historical_road_keeps_point_expansion_disabled(self):
        for road_id in ["1", "1300069"]:
            with self.subTest(road_id=road_id):
                initial = {road_id: {"D": {"10": [0, 10] + [0] * 8}}}
                report, updated, activated = self._run_raw_feedback_day(initial, road_id=road_id)
                self.assertEqual(report["status"], "completed_pool_updated_no_table_change")
                self.assertEqual(updated, initial)
                self.assertFalse(activated)
                self.assertGreater(report["candidate_count"], 0)

    def test_19_and_49_new_points_still_require_sample_threshold(self):
        for road in ("1700240", "1700125", "1700448"):
            with self.subTest(road=road):
                initial = {road: {"D": {"10": [0, 10] + [0] * 8}}}
                report, updated, activated = self._run_raw_feedback_day(
                    initial, minimum_samples=30, road_id=road,
                )
                self.assertGreater(report["candidate_count"], 0)
                self.assertEqual(updated, initial)
                self.assertFalse(activated)

    def test_skipped_missing_data_or_configuration_can_resume_after_repair(self):
        for reason in ["missing_source", "invalid_table", "missing_cross"]:
            with self.subTest(reason=reason):
                report, updated, activated = self._run_raw_feedback_day(
                    {}, resume_after_skip=reason,
                )
                self.assertEqual(report["status"], "completed_table_updated")
                self.assertTrue(activated)
                self.assertTrue(updated["1"]["U"])

    def test_completed_day_stays_idempotent(self):
        with mock.patch.object(RUNTIME, "normalize_raw_feedback",
                               wraps=RUNTIME.normalize_raw_feedback) as normalize:
            self._run_raw_feedback_day({}, repeat_completed=True)
        self.assertEqual(normalize.call_count, 1)

    def test_interrupted_publication_recovers_manifest_without_reblending(self):
        report, updated, activated = self._run_raw_feedback_day(
            {}, interrupt_publication=True,
        )
        self.assertTrue(activated)
        self.assertTrue(updated["1"]["U"])
        self.assertTrue(report["pool_summary"]["publication_recovery_required"])

    def test_same_date_can_add_other_roads_and_recheck_does_not_blend_twice(self):
        from lib.data_ANS.experience_reader import load_experience_table
        from lib.data_ANS.experience_release import _canonical_hash
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs_data"
            for kind in ("flow", "extend"):
                folder = logs / kind
                folder.mkdir(parents=True)
                (folder / f"2026-11-12_{kind}.txt").touch()
            active, cross = root / "active.json", root / "cross.json"
            active.write_text(json.dumps({"1700125": {"U": {"10": [0, 10] + [0] * 8}}}))
            cross.write_text(json.dumps({
                road: {"LaneNo": {"U": {"1": "1B"}}, "phase": {"1": "U"}, "Cycle": [[1]]}
                for road in ("1700240", "1700125")
            }))
            environment = {
                "AITC_EXPERIENCE_POOL_STATE_DIR": str(root / "state"),
                "AITC_EXPERIENCE_POOL_ARTIFACT_DIR": str(root / "daily"),
                "AITC_EXPERIENCE_RUNTIME_TABLE": str(active),
                "AITC_EXPERIENCE_CROSS_INFO": str(cross),
                "AITC_EXPERIENCE_VERSIONS_DIR": str(root / "versions"),
                "AITC_EXPERIENCE_MANIFEST": str(root / "versions" / "active_manifest.json"),
                "AITC_EXPERIENCE_POOL_MIN_SAMPLES": "1",
                "AITC_FLOW_ALLOCATOR_SHADOW_TABLE": "",
            }
            def observations(**kwargs):
                return [{
                    "CrossId": road, "direction": "U", "actual_green_time": 10,
                    "source_date": "2026-11-12", "source_window_start": 1000,
                    "quality_gate_passed": True, "capacity_lane_indexes": [1],
                    "candidate_observed_flow": [0, 50] + [0] * 8,
                } for road in kwargs["target_cross_ids"]], {}

            with mock.patch.object(RUNTIME, "LOGS_DIR", logs), mock.patch.dict(os.environ, environment), \
                    mock.patch.object(RUNTIME, "normalize_raw_feedback", side_effect=observations) as normalize:
                before = load_experience_table(road_id="1700125")["1700125"]["U"]["10"]
                for road in ("1700240", "1700125"):
                    with mock.patch.dict(os.environ, {
                        "AITC_EXPERIENCE_POOL_ROADS": road,
                        "AITC_EXPERIENCE_TABLE_UPDATE_ROADS": road,
                    }):
                        report = run_experience_pool_day("2026-11-12")
                        self.assertEqual(report["target_road_ids"], [road])
                        self.assertEqual(report["pool_summary"]["accumulation"]["accepted_samples"], 1)
                after = load_experience_table(road_id="1700125")["1700125"]["U"]["10"]
                self.assertNotEqual(before, after)
                self.assertEqual(after[1], 18)
                manifest = json.loads((root / "versions" / "active_manifest.json").read_text())
                self.assertEqual(manifest["active_sha256"], _canonical_hash(json.loads(active.read_text())))
                with mock.patch.dict(os.environ, {
                    "AITC_EXPERIENCE_POOL_ROADS": "1700125",
                    "AITC_EXPERIENCE_TABLE_UPDATE_ROADS": "1700125",
                }):
                    table_bytes = active.read_bytes()
                    run_experience_pool_day("2026-11-12")
                    self.assertEqual(normalize.call_count, 2)
                    rechecked = run_experience_pool_day("2026-11-12", recheck=True)
                self.assertEqual(normalize.call_count, 3)
                self.assertEqual(active.read_bytes(), table_bytes)
                self.assertFalse(rechecked["table_updated"])
                self.assertEqual(rechecked["pool_summary"]["days"]["2026-11-12"]["status"], "already_applied")
                pool = json.loads((root / "state" / "online_experience_samples.json").read_text())
                self.assertEqual(pool["state"]["daily_runs"]["2026-11-12"]["processed_road_ids"],
                                 ["1700125", "1700240"])

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
