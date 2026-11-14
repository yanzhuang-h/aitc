"""版本对比必须拒绝不同条件，并区分历史回归与新路口待验收。"""

import copy
import hashlib
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.compare_release_replays import compare_replays, main


def payload(road, duration=20):
    return {"additional": {"tlLogic": {
        "id": road, "programID": 1, "phase": [{"duration": duration}]}},
        "traffic_vector": [], "modelInfo": {"score": 90}}


class CompareReleaseReplaysTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.baseline = self.root / "baseline"
        self.candidate = self.root / "candidate"
        self.batch = [payload("1300068"), payload("1700125"), payload("1700314")]
        self.summary = {
            "seed": 37, "round_interval_seconds": 120, "model_enabled": False,
            "sources": [{"path": "/tmp/source.jsonl", "sha256": "a" * 64,
                         "loaded_records": 1, "limit_per_file": 100,
                         "truncated": False, "invalid_lines": 0,
                         "timestamp_bases": {"AITC_SYS_TS": 1}}],
            "configuration_files_at_start": {"lib/cross_info.json": "b" * 64},
            "rounds": [{"round": 1, "decision_time": 1000,
                        "ingested_total": 1, "result_count": 3}],
            "ingested_records": 1, "records_after_last_round": 0,
            "prediction_dir": None, "capture_provenance": "unit_test",
        }
        for root in (self.baseline, self.candidate):
            root.mkdir()
            self.write(root)

    def write(self, root, *, batches=None, summary=None):
        batches = [self.batch] if batches is None else batches
        summary = self.summary if summary is None else summary
        (root / "results.jsonl").write_text(
            "".join(json.dumps(batch) + "\n" for batch in batches))
        (root / "summary.json").write_text(json.dumps(summary))

    def compare(self):
        return compare_replays(self.baseline, self.candidate)

    def test_identical_output_never_proves_19_or_49_fixed(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                  for root in (self.baseline, self.candidate) for p in root.iterdir()}
        report = self.compare()
        self.assertEqual(report["status"], "identical_in_sample")
        self.assertTrue(report["groups"]["historical"]["identical_in_sample"])
        for group in ("19", "49"):
            self.assertTrue(report["groups"][group]["identical_in_sample"])
            self.assertFalse(report["groups"][group]["problem_resolution_verified"])
        self.assertFalse(report["field_effect_verified"])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_historical_and_problem_cohorts_have_separate_assessments(self):
        changed = [payload("1300068", 21), payload("1700125", 22), payload("1700314", 23)]
        self.write(self.candidate, batches=[changed])
        report = self.compare()
        self.assertEqual(report["status"], "differences")
        by_group = {item["group"]: item for item in report["changes"]}
        self.assertEqual(by_group["historical"]["assessment"], "historical_review_required")
        for group in ("19", "49"):
            self.assertEqual(by_group[group]["assessment"], "fix_acceptance_pending")
            self.assertEqual(by_group[group]["kind"], "control")
        self.assertEqual(by_group["historical"]["baseline_control"],
                         self.batch[0]["additional"])

    def test_diagnostic_changes_are_not_hidden_as_control_equivalence(self):
        changed = copy.deepcopy(self.batch)
        changed[0]["modelInfo"]["score"] = 80
        self.write(self.candidate, batches=[changed])
        report = self.compare()
        self.assertEqual(report["changes"][0]["kind"], "payload_metadata")
        self.assertFalse(report["groups"]["historical"]["identical_in_sample"])

    def test_numeric_type_changes_are_visible(self):
        changed = copy.deepcopy(self.batch)
        changed[0]["additional"]["tlLogic"]["phase"][0]["duration"] = 20.0
        self.write(self.candidate, batches=[changed])
        self.assertEqual(self.compare()["changes"][0]["kind"], "control")

    def test_invalid_counts_and_timeline_cannot_claim_matching_inputs(self):
        for patch in ({"seed": None}, {"seed": True},
                      {"round_interval_seconds": 0}, {"ingested_records": -1}):
            self.write(self.candidate, summary=self.summary | patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.compare()
        summary = copy.deepcopy(self.summary)
        summary["sources"][0]["loaded_records"] = 2
        self.write(self.candidate, summary=summary)
        with self.assertRaises(ValueError):
            self.compare()

    def test_missing_and_new_roads_are_reported_without_allowlisting_whole_groups(self):
        changed = [self.batch[0], self.batch[1], payload("2706152")]
        self.write(self.candidate, batches=[changed])
        report = self.compare()
        self.assertEqual({(row["road_id"], row["kind"]) for row in report["changes"]},
                         {("1700314", "missing"), ("2706152", "added")})

    def test_wire_order_change_is_not_silently_accepted(self):
        self.write(self.candidate, batches=[list(reversed(self.batch))])
        report = self.compare()
        self.assertEqual(report["changes"], [])
        self.assertEqual(len(report["order_changes"]), 1)
        self.assertEqual(report["status"], "differences")

    def test_recorded_input_configuration_clock_or_seed_differences_block_comparison(self):
        for field in ("sources", "configuration_files_at_start", "rounds", "seed"):
            summary = copy.deepcopy(self.summary)
            if field == "sources":
                summary[field][0]["sha256"] = "c" * 64
            elif field == "configuration_files_at_start":
                summary[field]["lib/cross_info.json"] = "c" * 64
            elif field == "rounds":
                summary[field][0]["decision_time"] += 1
            else:
                summary[field] += 1
            with self.subTest(field=field):
                self.write(self.candidate, summary=summary)
                report = self.compare()
                self.assertEqual(report["status"], "incomparable")
                self.assertFalse(report["groups"]["historical"]["identical_in_sample"])

    def test_source_path_difference_alone_does_not_invalidate_identical_capture(self):
        summary = copy.deepcopy(self.summary)
        summary["sources"][0]["path"] = "/other-machine/same-input.jsonl"
        self.write(self.candidate, summary=summary)
        self.assertEqual(self.compare()["status"], "identical_in_sample")

    def test_external_prediction_path_does_not_prove_same_contents(self):
        summary = copy.deepcopy(self.summary)
        summary["prediction_dir"] = "/same/path"
        for root in (self.baseline, self.candidate):
            self.write(root, summary=summary)
        self.assertIn("external_prediction_contents_unverified",
                      self.compare()["condition_mismatches"])

    def test_invalid_or_incomplete_metadata_fails(self):
        for update in ({"model_enabled": True}, {"sources": []},
                       {"configuration_files_at_start": {}}, {"rounds": []}):
            summary = self.summary | update
            self.write(self.candidate, summary=summary)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.compare()
        summary = copy.deepcopy(self.summary)
        del summary["seed"]
        self.write(self.candidate, summary=summary)
        with self.assertRaisesRegex(ValueError, "seed"):
            self.compare()

    def test_duplicate_empty_malformed_and_nonfinite_results_fail(self):
        for text in (
            json.dumps([self.batch[0], self.batch[0]]) + "\n",
            "[]\n", "", "{}\n", "[{}]\n",
            '[{"additional": {"tlLogic": {"id": "1"}}, "value": NaN}]\n',
        ):
            (self.candidate / "results.jsonl").write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.compare()

    def test_round_and_road_count_must_match_recorded_summary(self):
        for batches in ([self.batch, self.batch], [self.batch[:1]]):
            self.write(self.candidate, batches=batches)
            with self.subTest(batches=len(batches)), self.assertRaises(ValueError):
                self.compare()

    def test_no_unobserved_group_gets_a_pass(self):
        summary = copy.deepcopy(self.summary)
        summary["rounds"][0]["result_count"] = 1
        for root in (self.baseline, self.candidate):
            self.write(root, batches=[[self.batch[1]]], summary=summary)
        self.assertIsNone(self.compare()["groups"]["historical"]["identical_in_sample"])

    def test_cli_only_creates_new_reports_and_signals_differences(self):
        output = self.root / "report.json"
        args = ["--baseline", str(self.baseline), "--candidate", str(self.candidate),
                "--output", str(output)]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 0)
            content = output.read_bytes()
            self.assertEqual(main(args), 2)
            self.assertEqual(output.read_bytes(), content)
            self.write(self.candidate, batches=[[payload("1300068", 30), *self.batch[1:]]])
            self.assertEqual(main(args[:-2]), 1)


if __name__ == "__main__":
    unittest.main()
