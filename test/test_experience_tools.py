"""补训入口仅用mock和合成文件验证；不处理生产日志或活动经验池。"""

from contextlib import redirect_stdout
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib.data_ANS import experience_runtime as runtime
from lib.data_ANS.experience_release import _canonical_hash
from tools import backfill_experience as backfill
from tools import check_online_learning as check
from tools import run_experience_pool_now as single


class FixedDate(dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 17)


class ExperienceToolsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        cwd, search_path = Path.cwd(), list(sys.path)
        self.addCleanup(os.chdir, cwd)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), search_path))
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.enterContext(patch.object(runtime, "LOGS_DIR", self.root / "logs_data"))
        self.enterContext(patch.object(backfill.dt, "date", FixedDate))
        self.root.joinpath(".env").write_text("\n".join((
            "AITC_EXPERIENCE_POOL_STATE_DIR=state",
            "AITC_EXPERIENCE_POOL_ARTIFACT_DIR=daily",
            "AITC_EXPERIENCE_RUNTIME_TABLE=published.json",
            "AITC_EXPERIENCE_CROSS_INFO=cross.json",
            "AITC_EXPERIENCE_VERSIONS_DIR=versions",
            "AITC_EXPERIENCE_MANIFEST=versions/active_manifest.json",
            "AITC_FLOW_ALLOCATOR_SHADOW_LOG_DIR=shadow",
            "AITC_FLOW_ALLOCATOR_PILOT_MODE=legacy",
            "AITC_FLOW_ALLOCATOR_PILOT_ROADS=1700125",
        )))
        self.table = {"1700125": {"U": {"10": [0, 20] + [0] * 8}}}
        self.root.joinpath("published.json").write_text(json.dumps(self.table))
        versions = self.root / "versions"
        versions.mkdir()
        versions.joinpath("active_manifest.json").write_text(json.dumps({
            "active_sha256": _canonical_hash(self.table),
            "runtime_path": str(self.root / "published.json"),
        }))

    def invoke(self, module, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = module.main(["--root", str(self.root), *args])
        return code, output.getvalue()

    def test_default_week_preview_covers_19_and_49_without_running_or_writing(self):
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with patch.object(runtime, "run_experience_pool_day") as run, \
                patch.object(runtime, "_run_paths", wraps=runtime._run_paths) as paths:
            code, output = self.invoke(backfill)
        run.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual([str(call.args[0]) for call in paths.call_args_list],
                         [f"2026-11-{day:02d}" for day in range(10, 17)])
        roads = set(os.environ["AITC_EXPERIENCE_POOL_ROADS"].split(","))
        self.assertIn("1700125", roads)
        self.assertIn("1700240", roads)
        self.assertNotIn("1300068", roads)
        self.assertEqual(os.environ["AITC_EXPERIENCE_POOL_MIN_SAMPLES"], "30")
        self.assertIn(f"发布运行表: {self.root / 'published.json'}", output)
        self.assertIn(str(self.root / "versions" / "active_manifest.json"), output)
        after = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_explicit_dates_and_road_scope_are_preserved(self):
        with patch.object(runtime, "run_experience_pool_day", return_value={"status": "completed"}) as run:
            code, _output = self.invoke(
                backfill, "--start", "2026-11-12", "--end", "2026-11-13",
                "--roads", "1700125,1700240", "--apply",
            )
        self.assertEqual(code, 0)
        self.assertEqual([str(call.args[0]) for call in run.call_args_list], ["2026-11-12", "2026-11-13"])
        self.assertTrue(all(call.kwargs == {"recheck": False} for call in run.call_args_list))
        self.assertEqual(os.environ["AITC_EXPERIENCE_POOL_ROADS"], "1700125,1700240")

    def test_force_requests_locked_recheck_without_deleting_day_record(self):
        record = self.root / "state" / "runs" / "2026-11-16.json"
        record.parent.mkdir(parents=True)
        record.write_text('{"status":"completed","target_road_ids":["1700125"]}')
        original = record.read_bytes()
        with patch.object(runtime, "run_experience_pool_day",
                          return_value={"status": "skipped_missing_source_data"}) as run:
            code, _output = self.invoke(backfill, "--days", "1", "--roads", "19", "--force", "--apply")
        self.assertEqual(code, 1)
        self.assertEqual(run.call_args.kwargs, {"recheck": True})
        self.assertEqual(record.read_bytes(), original)
        self.assertIn("1700125", os.environ["AITC_EXPERIENCE_POOL_ROADS"].split(","))

    def test_existing_environment_overrides_dotenv_and_reports_different_read_table(self):
        os.environ["AITC_EXPERIENCE_RUNTIME_TABLE"] = "explicit.json"
        os.environ["AITC_FLOW_ALLOCATOR_SHADOW_TABLE"] = "comparison.json"
        _code, output = self.invoke(backfill, "--days", "1", "--roads", "49")
        self.assertIn(f"发布运行表: {self.root / 'explicit.json'}", output)
        self.assertIn(f"分配器实际读取另一份表: {self.root / 'comparison.json'}", output)
        self.assertNotIn("1700125", os.environ["AITC_EXPERIENCE_POOL_ROADS"].split(","))

    def test_all_keeps_legacy_registration_scope(self):
        folder = self.root / "lib"
        folder.mkdir()
        folder.joinpath("plan_id_overrides.json").write_text('{"1700240": 1}')
        _code, _output = self.invoke(backfill, "--days", "1", "--roads", "all")
        self.assertEqual(os.environ["AITC_EXPERIENCE_POOL_ROADS"], "1700240")

    def test_invalid_ranges_or_thresholds_fail_before_execution(self):
        cases = [
            ["--start", "2026-11-12"],
            ["--start", "2026-11-13", "--end", "2026-11-12"],
            ["--start", "2026-11-12", "--end", "2026-11-13", "--days", "7"],
            ["--days", "0"], ["--min-samples", "0"], ["--roads", ",,"],
        ]
        for args in cases:
            with self.subTest(args=args), patch.object(runtime, "run_experience_pool_day") as run, \
                    redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.invoke(backfill, *args)
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()

    def test_single_day_tool_delegates_to_shared_production_defaults(self):
        with patch.object(backfill, "main", return_value=0) as delegate:
            code = single.main(["--root", str(self.root)])
        self.assertEqual(code, 0)
        args = delegate.call_args.args[0]
        self.assertEqual(args[args.index("--start") + 1], "2026-11-16")
        self.assertEqual(args[args.index("--end") + 1], "2026-11-16")
        self.assertEqual(args[args.index("--min-samples") + 1], "30")
        self.assertIn("--apply", args)

    def test_streaming_helpers_keep_only_latest_road_record_and_count_bad_lines(self):
        shadow = self.root / "shadow"
        shadow.mkdir()
        latest = shadow / "flow_time_allocator_2026-11-16.jsonl"
        latest.write_text('\n'.join((
            '{"road_id":"1700125","selected_schedule_source":"legacy"}',
            '{"road_id":"1700125","selected_schedule_source":"new"}',
            '[]', '{"unfinished":',
        )))
        log = self.root / "server.log"
        log.write_text('prefix {"fallback_source": "timetable"}\nprefix {"fallback_source":"timetable"}\n')
        with patch.object(Path, "read_text", side_effect=AssertionError("large logs must stream")):
            file, summary, invalid = check._load_shadow_summary(shadow)
            fallback = check._fallback_stats(log)
        self.assertEqual(file, latest)
        self.assertEqual(summary["1700125"]["count"], 2)
        self.assertEqual(summary["1700125"]["last"]["selected_schedule_source"], "new")
        self.assertEqual(invalid, 2)
        self.assertEqual(fallback["timetable"], 2)

    def test_diagnostic_checks_release_and_task_holes_even_without_shadow_log(self):
        (self.root / "AITC.log").touch()
        (self.root / "server.log").write_text('prefix {"fallback_source":"timetable"}\n')
        record = self.root / "state" / "runs" / "2026-11-16.json"
        record.parent.mkdir(parents=True)
        record.write_text('{"status":"completed_no_qualified_samples","target_road_ids":["1700240"]}')
        with patch.object(runtime, "run_experience_pool_day") as run:
            code, output = self.invoke(check, "--cross", "1700125")
        run.assert_not_called()
        self.assertIn("fallback_source: timetable=1", output)
        self.assertEqual(code, 0)
        self.assertIn("pilot mode: legacy，目标路口数: 1", output)
        self.assertIn("最新文件: 未找到", output)
        self.assertIn("与发布表一致: True", output)
        self.assertIn("【19组】1700125", output)
        self.assertIn("2026-11-15 无日任务记录", output)
        self.assertIn("未覆盖=1700125", output)

    def test_diagnostic_compares_latest_log_to_configured_read_table(self):
        comparison = {"1700125": {"U": {"20": [0, 40] + [0] * 8}}}
        self.root.joinpath("comparison.json").write_text(json.dumps(comparison))
        os.environ["AITC_FLOW_ALLOCATOR_SHADOW_TABLE"] = "comparison.json"
        folder = self.root / "shadow"
        folder.mkdir()
        folder.joinpath("flow_time_allocator_2026-11-16.jsonl").write_text(json.dumps({
            "road_id": "1700125", "experience_road_sha256": _canonical_hash(comparison["1700125"]),
        }))
        _code, output = self.invoke(check, "--cross", "1700125")
        self.assertIn("发布表与分配器读取路径不同", output)
        self.assertIn("最新日志经验指纹与当前读取文件一致: True", output)


if __name__ == "__main__":
    unittest.main()
