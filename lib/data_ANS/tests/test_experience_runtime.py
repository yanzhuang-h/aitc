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

    def test_scheduler_latest_source_is_yesterday(self):
        self.assertEqual(
            ExperiencePoolScheduler.source_date_for_run(
                dt.date(2026, 11, 19)
            ),
            dt.date(2026, 11, 18),
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

    def test_startup_catchup_defaults_to_five_minutes_in_production(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ExperiencePoolScheduler().initial_delay_seconds(), 300)
            self.assertEqual(ExperiencePoolScheduler(production=False).initial_delay_seconds(), 0)
        with mock.patch.dict(os.environ, {"AITC_EXPERIENCE_POOL_INITIAL_DELAY_SECONDS": "0"}):
            self.assertEqual(ExperiencePoolScheduler().initial_delay_seconds(), 0)

    def test_startup_and_noon_use_same_catchup(self):
        scheduler = ExperiencePoolScheduler()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(scheduler._stop_event, "wait", side_effect=(False, False, True)) as wait,
            mock.patch.object(scheduler, "run_catchup") as catchup,
        ):
            scheduler._run_loop()
        self.assertEqual(wait.call_args_list[0].args, (300,))
        self.assertEqual(catchup.call_args_list, [mock.call(startup=True), mock.call()])

    def test_catchup_pairs_the_last_ten_days_and_skips_partial_sources(self):
        run_date = dt.date(2026, 11, 19)
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            for kind in ("flow", "extend"):
                (logs / kind).mkdir()
            for day in (9, 10, 17, 18, 19):
                source = dt.date(2026, 11, day)
                _, end = RUNTIME._source_day_bounds(source)
                for kind in ("flow", "extend"):
                    if day == 10 and kind == "extend":
                        continue
                    timestamp = end - 18_000 if day == 17 else end - 2
                    (logs / kind / f"{source}_{kind}.txt").write_text(
                        json.dumps({"AITC_SYS_TS": timestamp}) + "\n", encoding="utf-8",
                    )
            scheduler = ExperiencePoolScheduler(log_dir=logs)
            with (
                self.assertLogs("ExperiencePoolRuntime", level="INFO") as captured,
                mock.patch.object(scheduler, "run_for_date", side_effect=(
                    {"status": "completed_table_updated", "table_updated": True},
                    {"status": "completed_table_updated", "table_updated": True, "report_reused": True},
                )) as run_day,
            ):
                report = scheduler.run_catchup(run_date, startup=True)
            progress = [entry.getMessage() for entry in captured.records[:-1]]
            self.assertEqual(len(progress), 11)
            self.assertIn("启动预热补训 [----------] 已检查 0/10", progress[0])
            self.assertIn("[#---------] 已检查 1/10 2026-11-09 已发布经验表", progress[1])
            self.assertIn("[##--------] 已检查 2/10 2026-11-10 待数据收齐", progress[2])
            self.assertIn("[##########] 已检查 10/10 2026-11-18 复用已有日记录", progress[-1])
            self.assertEqual(list(report), [f"2026-11-{day:02d}" for day in range(9, 19)])
            self.assertEqual(run_day.call_args_list, [
                mock.call(source_date=dt.date(2026, 11, 9)),
                mock.call(source_date=dt.date(2026, 11, 18)),
            ])
            self.assertEqual(report["2026-11-10"]["missing"], ["extend"])
            self.assertEqual(report["2026-11-17"]["incomplete"], ["flow", "extend"])
            self.assertEqual(report["2026-11-18"], {
                "status": "reused_existing_report",
                "previous_status": "completed_table_updated",
                "pool_committed": False,
                "table_updated": False,
            })

    def test_catchup_stops_after_failed_ready_day(self):
        scheduler = ExperiencePoolScheduler()
        with (
            self.assertLogs("ExperiencePoolRuntime", level="INFO") as captured,
            mock.patch.object(RUNTIME, "_source_pair_status", return_value=None),
            mock.patch.object(scheduler, "run_for_date", return_value=None) as run_day,
        ):
            report = scheduler.run_catchup(dt.date(2026, 11, 19))
        self.assertIn("定时补训 [#---------] 已检查 1/10 2026-11-09 任务失败或已在运行，本轮结束",
                      captured.records[-2].getMessage())
        run_day.assert_called_once_with(source_date=dt.date(2026, 11, 9))
        self.assertEqual(report, {"2026-11-09": {"status": "run_failed_or_busy"}})

    def test_scheduler_can_run_an_explicit_source_date_for_testing(self):
        scheduler = ExperiencePoolScheduler()
        with mock.patch.object(
            RUNTIME,
            "run_experience_pool_day",
            return_value={"status": "completed"},
        ) as run_day:
            scheduler.run_for_date(source_date="2026-07-17")

        run_day.assert_called_once_with(dt.date(2026, 7, 17), release_settings=None, log_dir=None)

    def test_missing_source_files_are_skipped_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ,
                {"AITC_EXPERIENCE_POOL_STATE_DIR": directory},
            ):
                first = run_experience_pool_day("2099-01-01")
                second = run_experience_pool_day("2099-01-01")

            self.assertEqual(second, {**first, "report_reused": True})
            self.assertEqual(first["status"], "skipped_missing_source_data")
            manifest = Path(directory) / "runs" / "2099-01-01.json"
            self.assertTrue(manifest.exists())
            self.assertFalse(first["pool_committed"])
            self.assertFalse(first["table_updated"])

    def _run_raw_feedback_day(self, initial_table, minimum_samples=1, road_id="1",
                              resume_after_skip=None, repeat_completed=False, interrupt_publication=False,
                              missing_road=None):
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
            if missing_road:
                for key in ("AITC_EXPERIENCE_POOL_ROADS", "AITC_EXPERIENCE_TABLE_UPDATE_ROADS"):
                    environment[key] = f"{road_id},{missing_road}"
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
                    day_report = state_dir / "runs" / f"{source_date}.json"
                    report_bytes = day_report.read_bytes()
                    logger = mock.Mock()
                    reused = ExperiencePoolScheduler(logger=logger).run_for_date(source_date=source_date)
                    self.assertEqual(reused, {**report, "report_reused": True})
                    summary = json.loads(logger.info.call_args.args[1])
                    self.assertEqual(summary["status"], "reused_existing_report")
                    self.assertEqual(summary["previous_status"], report["status"])
                    self.assertFalse(summary["pool_committed"])
                    self.assertFalse(summary["table_updated"])
                    self.assertEqual(summary["accumulation"], {})
                    self.assertEqual(day_report.read_bytes(), report_bytes)
                    self.assertEqual(runtime_path.read_bytes(), table_bytes)
                    self.assertEqual(pool_path.read_bytes(), pool_bytes)
                if missing_road:
                    # 补齐配置、重放同一日时，应处理新路口，已入池路口不再加权。
                    cross_info[missing_road] = {
                        **cross_info[road_id], "jtll_ddbh": {"12": "U", "13": "D"},
                    }
                    cross_info_path.write_text(json.dumps(cross_info))
                    for name, rows in (("flow", flow_rows), ("extend", extend_rows)):
                        path = logs / name / f"2026-07-24_{name}.txt"
                        duplicated = [
                            {**row, "jtll_ddbh": str(int(row["jtll_ddbh"]) + 2)}
                            if name == "flow" else {**row, "CrossId": missing_road}
                            for row in rows
                        ]
                        with path.open("a") as stream:
                            stream.write("\n" + "\n".join(json.dumps(row) for row in duplicated))
                    resumed = run_experience_pool_day(source_date)
                    self.assertEqual(resumed["status"], "completed_table_updated")
                    self.assertNotIn("missing_crosses", resumed)
                    self.assertEqual(resumed["target_road_ids"], [road_id, missing_road])
                    self.assertEqual(json.loads(runtime_path.read_text())[road_id],
                                     json.loads(table_bytes)[road_id])

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

    def test_missing_config_only_skips_the_affected_road_until_restored(self):
        with mock.patch.object(RUNTIME, "normalize_raw_feedback",
                               wraps=RUNTIME.normalize_raw_feedback) as normalize:
            report, updated, activated = self._run_raw_feedback_day(
                {}, road_id="1700125", missing_road="1700458", repeat_completed=True,
            )
        self.assertEqual(report["status"], "completed_table_updated")
        self.assertEqual(report["missing_crosses"], ["1700458"])
        self.assertEqual(report["table_update_road_ids"], ["1700125"])
        self.assertEqual(set(updated), {"1700125", "1700458"})
        self.assertTrue(activated)
        self.assertEqual([call.kwargs["target_cross_ids"] for call in normalize.call_args_list],
                         [["1700125"], ["1700125", "1700458"]])

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

    def test_late_source_isolated_to_roads_with_newer_pool_records(self):
        road_already_ahead, road_with_old_samples, road_without_old_samples = roads = (
            "1700125", "1700240", "2703320",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            for kind in ("flow", "extend"):
                folder = logs / kind
                folder.mkdir(parents=True)
                for day in ("2026-11-09", "2026-11-18"):
                    (folder / f"{day}_{kind}.txt").touch()
            active, cross = root / "active.json", root / "cross.json"
            cross.write_text(json.dumps({
                road: {"LaneNo": {"U": {"1": "1B"}}, "phase": {"1": "U"}, "Cycle": [[1]]}
                for road in roads
            }), encoding="utf-8")
            environment = {
                "AITC_EXPERIENCE_POOL_STATE_DIR": str(root / "state"),
                "AITC_EXPERIENCE_POOL_ARTIFACT_DIR": str(root / "daily"),
                "AITC_EXPERIENCE_RUNTIME_TABLE": str(active),
                "AITC_EXPERIENCE_CROSS_INFO": str(cross),
                "AITC_EXPERIENCE_VERSIONS_DIR": str(root / "versions"),
                "AITC_EXPERIENCE_MANIFEST": str(root / "versions" / "active_manifest.json"),
                "AITC_EXPERIENCE_POOL_MIN_SAMPLES": "1",
            }
            def observations(**kwargs):
                return [{
                    "CrossId": road, "direction": "U", "actual_green_time": 10,
                    "source_date": kwargs["source_date"], "source_window_start": kwargs["start_time"],
                    "quality_gate_passed": True, "capacity_lane_indexes": [1],
                    "candidate_observed_flow": [0, 50] + [0] * 8,
                } for road in kwargs["target_cross_ids"]
                    if kwargs["source_date"] != "2026-11-09" or road != road_without_old_samples], {}

            with (
                mock.patch.dict(os.environ, environment),
                mock.patch.object(RUNTIME, "normalize_raw_feedback", side_effect=observations) as normalize,
            ):
                with mock.patch.dict(os.environ, {
                    "AITC_EXPERIENCE_POOL_ROADS": road_already_ahead,
                    "AITC_EXPERIENCE_TABLE_UPDATE_ROADS": road_already_ahead,
                }):
                    run_experience_pool_day("2026-11-18", log_dir=logs)
                before = json.loads(active.read_text())[road_already_ahead]
                with mock.patch.dict(os.environ, {
                    "AITC_EXPERIENCE_POOL_ROADS": ",".join(roads),
                    "AITC_EXPERIENCE_TABLE_UPDATE_ROADS": ",".join(roads),
                }):
                    first = run_experience_pool_day("2026-11-09", log_dir=logs)
                    self.assertEqual(first["rebuild_required_roads"], [road_already_ahead])
                    self.assertEqual(first["target_road_ids"], [road_with_old_samples, road_without_old_samples])
                    old_table = json.loads(active.read_text())
                    self.assertEqual(old_table[road_already_ahead], before)
                    self.assertEqual(old_table[road_with_old_samples]["U"]["10"][1], 50)
                    self.assertNotIn(road_without_old_samples, old_table)
                    self.assertEqual(run_experience_pool_day("2026-11-09", log_dir=logs),
                                     {**first, "report_reused": True})
                    self.assertEqual(normalize.call_count, 2)

                    run_experience_pool_day("2026-11-18", log_dir=logs)
                    self.assertIn(road_without_old_samples, json.loads(active.read_text()))
                    repeated = run_experience_pool_day("2026-11-09", log_dir=logs)
            self.assertEqual(normalize.call_count, 3)
            self.assertEqual(repeated, {**first, "report_reused": True})

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
