import argparse
import datetime as dt
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lib.data_ANS.experience_release import _canonical_hash
from tools.check_online_learning import _export_evidence


class OnlineEvidenceExportTest(unittest.TestCase):
    def test_links_updated_row_to_adoption_and_keeps_send_frame_counts_separate(self):
        road = "1700124"
        start = dt.datetime.fromisoformat("2026-11-19T16:05:00+08:00")
        end = start + dt.timedelta(minutes=20)
        table = {road: {"U": {"30": [3], "31": [4]}}}
        previous = {road: {"U": {"30": [2], "31": [4]}}}
        sample = {road: {"directions": {"U": {"30": [{}, {}]}}}}
        plan = {"id": road, "programID": 1, "phase": [{"duration": 30}]}

        with TemporaryDirectory() as folder:
            root = Path(folder)

            def write(file, value):
                path = root / file
                path.write_text(json.dumps(value), encoding="utf8")
                return path

            table_path = write("table.json", table)
            previous_path = write("previous.json", previous)
            manifest = write("manifest.json", {
                "release_id": "active", "runtime_path": str(table_path), "active_sha256": _canonical_hash(table),
                "previous_sha256": _canonical_hash(previous), "rollback_version_path": str(previous_path),
                "created_at_utc": (start + dt.timedelta(minutes=1)).isoformat(),
                "source_metadata": {"source_date": "2026-11-18"},
            })
            daily = write("daily.json", {"status": "completed_table_updated",
                "pool_collection_road_ids": [road], "table_updated": True, "release": {"release_id": "active"}})
            samples = write("samples.json", {"roads": sample})

            candidate = {"road_id": road, "batch_id": "batch", "runtime_mode": "new",
                         "selected_schedule_source": "new", "experience_road_sha256": _canonical_hash(table[road]),
                         "decisions": {"U": {"requested_flow": 8, "table_green_time": 30}}}
            (root / "flow_time_allocator_2026-11-19.jsonl").write_text(
                "\n".join(json.dumps({**candidate, "observed_at": t.isoformat()}) for t in
                          (start, start + dt.timedelta(minutes=2), end)) + "\n",
                encoding="utf8",
            )
            unchanged = {**candidate, "observed_at": (start + dt.timedelta(minutes=3)).isoformat(),
                         "decisions": {"U": {"requested_flow": 10, "table_green_time": 31}}}
            with (root / "flow_time_allocator_2026-11-19.jsonl").open("a", encoding="utf8") as log:
                log.write(json.dumps(unchanged) + "\n")
            decision = root / "server.log"
            decision.write_text("INFO " + json.dumps({"event": "aitc.decision", "intersection_id": road,
                "batch_id": "batch", "status": "published", "plan_sha256": _canonical_hash(plan)}), encoding="utf8")
            (root / "2026-11-19_send.txt").write_text(
                "\n".join(json.dumps({"AITC_SYS_TS": (start + dt.timedelta(seconds=120 + i)).timestamp(),
                    "additional": {"tlLogic": plan}}) for i in range(2)) + "\n", encoding="utf8",
            )

            runtime = SimpleNamespace(DEFAULT_CATCHUP_DAYS=1,
                _run_paths=lambda *args, **kw: {"run_manifest": daily, "candidates": samples},
                _source_pair_status=lambda *args: None)
            shadow = SimpleNamespace(_target_road_ids=lambda: {road}, _pilot_mode=lambda _: "new")
            with patch("lib.data_ANS.experience_reader.runtime_experience_path", return_value=table_path):
                result = _export_evidence(argparse.Namespace(start=start, end=end, cross=[road]),
                    root, root, decision, runtime, shadow, SimpleNamespace(active_manifest_path=manifest),
                    lambda _: "19")

        self.assertTrue(result["active_manifest_matches_read_table"])
        self.assertEqual(result["source_days"][0]["roads"][road]["qualified_samples"], 2)
        report = result["roads"][road]
        self.assertEqual(report["candidate_rounds"], 3)
        self.assertEqual(report["current_release_row_seen_rounds"], 2)
        self.assertEqual(report["used_changed_experience_rounds"], 1)
        self.assertEqual(report["send_records"], 2)
        self.assertEqual(report["distinct_sent_plans_matching_final"], 1)
