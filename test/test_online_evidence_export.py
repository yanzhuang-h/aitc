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
        self.assertEqual(report["sent_program_counts"], {"1": 2})
        self.assertIsNone(report["latest_send"]["decision"])

    def test_joins_latest_send_by_batch_when_different_decisions_share_the_same_plan(self):
        road = "1700311"
        start = dt.datetime.fromisoformat("2026-11-19T16:05:00+08:00")
        end = start + dt.timedelta(minutes=2)
        plan = {"id": road, "programID": 1, "phase": [{"duration": 38}, {"duration": 37}]}
        fingerprint = _canonical_hash(plan)

        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "flow_time_allocator_2026-11-19.jsonl").write_text(
                "\n".join(json.dumps({
                    "road_id": road, "batch_id": batch, "observed_at": stamp.isoformat(),
                    "selected_schedule_source": source, "selection_fallback_reason": rejection,
                }) for batch, stamp, source, rejection in (
                    ("selected-new", start, "new", None),
                    ("sent-fallback", start - dt.timedelta(seconds=1), "legacy", "empty_flow"),
                )),
                encoding="utf-8",
            )
            decision = root / "server.log"
            decision_text = "\n".join("INFO " + json.dumps({
                "event": "aitc.decision", "intersection_id": road, "batch_id": batch,
                "status": "published", "plan_sha256": fingerprint, "safety_report": safety,
            }) for batch, safety in (
                ("selected-new", {"safety_status": "valid"}),
                ("sent-fallback", {"safety_status": "valid", "fallback_source": "timetable",
                                   "fallback_reason": ["invalid_signal_plan_contract"]}),
            ))
            decision.write_text(decision_text + "\nINFO flow_control " + json.dumps({
                "cross_id": road, "batch_id": "sent-fallback", "fallback": "time_schedule",
            }), encoding="utf-8")
            send_path = root / "2026-11-19_send.txt"
            send_path.write_text("\n".join(json.dumps({
                "AITC_SYS_TS": (start + dt.timedelta(seconds=seconds)).timestamp(),
                "AITC_DECISION_BATCH_ID": "sent-fallback", "additional": {"tlLogic": outbound},
            }) for seconds, outbound in (
                (1, {**plan, "programID": 0, "phase": []}),
                (2, {**plan, "programID": 0}),
                (3, plan),
            )), encoding="utf-8")
            runtime = SimpleNamespace(DEFAULT_CATCHUP_DAYS=0)
            shadow = SimpleNamespace(_target_road_ids=lambda: {road}, _pilot_mode=lambda _: "new")
            with patch("lib.data_ANS.experience_reader.runtime_experience_path", return_value=root / "absent"):
                result = _export_evidence(argparse.Namespace(start=start, end=end, cross=[road]),
                    root, root, decision, runtime, shadow, SimpleNamespace(active_manifest_path=root / "absent"),
                    lambda _: "49")
        report = result["roads"][road]
        self.assertEqual(report["sent_program_counts"], {"0": 1, "1": 1})
        self.assertEqual(report["empty_phase_send_records"], 1)
        self.assertEqual(report["new_selected_rounds"], 1)
        self.assertEqual(report["distinct_sent_plans_matching_final"], 0)
        latest = report["latest_send"]
        self.assertEqual(latest["batch_id"], "sent-fallback")
        self.assertEqual(latest["program_id"], 1)
        self.assertEqual(latest["green_seconds"], [38, 37])
        self.assertEqual(latest["decision"]["candidate_source"], "legacy")
        self.assertEqual(latest["decision"]["candidate_rejection_reason"], "empty_flow")
        self.assertEqual(latest["decision"]["safety_fallback_source"], "timetable")
        self.assertEqual(latest["decision"]["coordinator_fallback"], "time_schedule")
