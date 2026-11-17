"""发布在线经验可热更新，历史底表和零值语义保持明确。"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lib import intersection_strategy as strategy
from lib.data_ANS import experience_reader as reader
from lib.data_ANS.flow_time_allocator import allocate_from_runtime_data


def vector(value):
    return [value]+[0]*9


class ExperienceReaderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.offline = self.root/"offline.json"
        self.online = self.root/"online.json"
        self.offline.write_text(json.dumps({
            "old": {"U": {"100": vector(100), "20": vector(20)}, "LTL": {"25": vector(25)}},
            "new": {"U": {"20": vector(999)}},
        }))
        self.online.write_text(json.dumps({"old": {"U": {"20": vector(0), "30": vector(30)}}}))
        self.enterContext(patch.object(strategy, "PLATFORM_PHASE_ROAD_IDS", {"new"}))
        self.enterContext(patch.dict("os.environ", {"AITC_EXPERIENCE_RUNTIME_TABLE": str(self.online)}, clear=True))

    def load(self, **kwargs):
        return reader.load_experience_table(offline_path=self.offline, **kwargs)

    def test_historical_point_overlay_preserves_zero_and_other_directions(self):
        merged = self.load(road_id="old")["old"]
        self.assertEqual(list(merged["U"]), ["20", "30", "100"])
        self.assertEqual(merged["U"]["20"], vector(0))
        self.assertEqual(merged["U"]["100"], vector(100))
        self.assertEqual(merged["LTL"]["25"], vector(25))
        # 返回结果可由旧调用者修改，不能污染下一次读取的缓存。
        merged["U"]["20"][0] = 900
        self.assertEqual(self.load(road_id="old")["old"]["U"]["20"], vector(0))

    def test_platform_road_never_uses_or_reads_offline_file(self):
        self.offline.write_text("不是 JSON")
        self.assertEqual(self.load(road_id="new"), {})
        self.online.write_text(json.dumps({"new": {"U": {"35": vector(45)}}}))
        self.assertEqual(self.load(road_id="new"), {"new": {"U": {"35": vector(45)}}})

    def test_missing_online_keeps_history_and_empty_new_road(self):
        self.online.unlink()
        self.assertEqual(self.load(road_id="old")["old"]["LTL"]["25"], vector(25))
        self.assertEqual(self.load(road_id="new"), {})
        self.assertTrue(self.load(road_id="old")["old"]["U"])

    def test_missing_historical_online_source_retains_existing_error_fallback(self):
        self.online.unlink()
        with self.assertRaises(FileNotFoundError):
            reader.load_experience_table(road_id="old")
        self.assertEqual(reader.load_experience_table(road_id="new"), {})

    def test_atomic_publish_and_rollback_refresh_without_restart(self):
        original_stat = self.online.stat()
        replacement = self.root/"published.json"
        replacement.write_text(self.online.read_text().replace("[30,", "[35,"))
        os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        first = self.load(road_id="old")["old"]["U"]["30"]
        os.replace(replacement, self.online)
        self.assertEqual(first, vector(30))
        self.assertEqual(self.load(road_id="old")["old"]["U"]["30"], vector(35))
        self.online.write_text(json.dumps({"old": {"U": {"30": vector(30)}}}))
        self.assertEqual(self.load(road_id="old")["old"]["U"]["30"], vector(30))

    def test_explicit_allocator_table_takes_precedence(self):
        other = self.root/"other.json"
        other.write_text('{"old": {"U": {"42": [9]}}}')
        with patch.dict("os.environ", {"AITC_FLOW_ALLOCATOR_SHADOW_TABLE": str(other)}):
            self.assertEqual(reader.runtime_experience_path(), other)
            self.assertEqual(list(self.load(road_id="old")["old"]["U"]), ["20","42","100"])

    def test_legacy_algorithms_share_reader_and_retain_own_offline_paths(self):
        from lib import movement_experience_timing as movement, cycle_experience_timing as cycle
        other = self.root/"cycle.json"
        other.write_text('{"old": {"D": {"50": [51]}}}')
        with patch.object(movement, "JIYAN_PATH", str(self.offline)), \
                patch.object(cycle, "JIYAN_PATH", str(other)):
            self.assertEqual(movement.jiangyan_biao_get("old")["LTL"]["25"], vector(25))
            self.assertEqual(cycle.load_jiyan()["old"]["D"]["50"], [51])
            self.assertNotIn("U", cycle.load_jiyan()["old"])
            self.assertEqual(movement.jiangyan_biao_get("old")["U"]["20"], vector(20))
            self.online.write_text("坏 JSON")
            self.assertEqual(movement.jiangyan_biao_get("old")["U"]["20"], vector(20))
            self.assertNotIn("LTL", cycle.load_jiyan()["old"])

    def test_direct_allocator_uses_runtime_table_from_first_run_and_sees_new_points(self):
        cross = {"new": {"phase": {"1": "U"}, "LaneNo": {"U": {"0": "1B"}},
                         "Cycle": [[1]]}}
        flow = {i: {"pass": {"U": [1]+[0]*6, "D": [0]*7, "L": [0]*7, "R": [0]*7}}
                for i in range(1, 601)}
        stages = {i: [{"CrossId": "new", "curStageNo": "1"}] for i in range(1, 601)}
        cold = allocate_from_runtime_data("new", flow, stages, cross_info=cross)
        self.assertEqual(cold["time_vector"][0], 30)
        self.online.write_text(json.dumps({"new": {"U": {"45": vector(1000)}}}))
        warm = allocate_from_runtime_data("new", flow, stages, cross_info=cross)
        self.assertEqual(warm["time_vector"][0], 45)

    def test_malformed_published_table_is_not_silently_used_as_experience(self):
        self.online.write_text("坏 JSON")
        with self.assertRaises(json.JSONDecodeError):
            self.load(road_id="old")


if __name__ == "__main__":
    unittest.main()
