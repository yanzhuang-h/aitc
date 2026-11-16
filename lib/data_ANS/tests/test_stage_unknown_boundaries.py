import json
from pathlib import Path
import tempfile
import unittest

from lib.data_ANS.flow_time_allocator import normalize_runtime_extend
from lib.data_ANS.raw_data_cleaning import clean_stage_inputs


class StageUnknownBoundaryTests(unittest.TestCase):
    def clean_both(self, observations):
        rows = [{"CrossId": "x", "time": timestamp, "curStageNo": stage}
                for timestamp, stage in observations]
        runtime = {}
        for row in rows:
            runtime.setdefault(row["time"], []).append(row)
        online, online_report = normalize_runtime_extend("x", runtime)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "extend.txt"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            training, report = clean_stage_inputs(
                str(path), {"x": {"phase": {"1": "UD", "2": "LR"}}},
                target_cross_ids={"x"},
            )
        return training["x"], online, report["crosses"]["x"], online_report

    def test_conflicting_second_and_following_gap_remain_unknown(self):
        training, online, report, online_report = self.clean_both([
            (100, 1), (101, 1), (101, 2), (104, 2),
        ])
        expected = {100: "1", 101: "-1", 102: "-1", 103: "-1", 104: "2"}
        self.assertEqual(training, expected)
        self.assertEqual(online, expected)
        self.assertEqual(report["stage_coverage"]["conflicting_seconds"], 1)
        self.assertEqual(report["stage_coverage"]["inherited_minus_one_seconds"], 0)
        self.assertEqual(online_report["conflicting_seconds"], 1)

    def test_conflict_cannot_be_erased_by_duplicate_valid_records(self):
        for values in [(1, 2, 1), (2, 1, 2), (1, 1, 2)]:
            with self.subTest(values=values):
                observations = [(100, 1)] + [(101, value) for value in values] + [(102, 2)]
                training, online, _, _ = self.clean_both(observations)
                self.assertEqual(training[101], "-1")
                self.assertEqual(online[101], "-1")

    def test_invalid_payload_blocks_inheritance_until_next_valid_stage(self):
        training, online, report, online_report = self.clean_both([
            (100, 1), (101, "bad"), (104, 2),
        ])
        expected = {100: "1", 101: "-1", 102: "-1", 103: "-1", 104: "2"}
        self.assertEqual(training, expected)
        self.assertEqual(online, expected)
        self.assertEqual(report["stage_coverage"]["invalid_stage_seconds"], 1)
        self.assertEqual(online_report["invalid_stage_seconds"], 1)

    def test_invalid_and_valid_payload_at_same_second_are_order_independent(self):
        for values in [("bad", 1), (1, "bad")]:
            with self.subTest(values=values):
                training, online, _, _ = self.clean_both(
                    [(100, 1)] + [(101, value) for value in values] + [(102, 2)]
                )
                self.assertEqual(training[101], "-1")
                self.assertEqual(online[101], "-1")

    def test_unconfigured_training_stage_is_not_inherited(self):
        training, _, report, _ = self.clean_both([
            (100, 1), (101, 99), (102, -1), (104, 2),
        ])
        self.assertEqual([training[t] for t in [101, 102, 103]], ["-1"] * 3)
        self.assertEqual(report["stage_coverage"]["invalid_stage_seconds"], 1)

    def test_long_gap_then_minus_one_cannot_resurrect_old_stage(self):
        training, online, _, _ = self.clean_both([
            (100, 1), (106, -1), (108, 2),
        ])
        expected = {100: "1", 101: "1", 102: "1", 103: "1",
                    104: "-1", 105: "-1", 106: "-1", 107: "-1", 108: "2"}
        self.assertEqual(training, expected)
        self.assertEqual(online, expected)

    def test_explicit_minus_one_after_conflict_remains_unknown(self):
        training, online, _, _ = self.clean_both([
            (100, 1), (101, 1), (101, 2), (102, -1), (104, 2),
        ])
        self.assertEqual([training[t] for t in [101, 102, 103]], ["-1"] * 3)
        self.assertEqual([online[t] for t in [101, 102, 103]], ["-1"] * 3)

    def test_ordinary_transitions_short_gaps_and_minus_one_keep_existing_behavior(self):
        training, online, _, _ = self.clean_both([
            (100, 1), (101, -1), (103, 2), (107, 1),
        ])
        expected = {100: "1", 101: "1", 102: "1", 103: "2",
                    104: "2", 105: "2", 106: "2", 107: "1"}
        self.assertEqual(training, expected)
        self.assertEqual(online, expected)

    def test_invalid_stage_numbers_do_not_raise_or_truncate_to_valid_stage(self):
        for invalid in [float("inf"), float("-inf"), float("nan"), 1.9, True, 10 ** 400]:
            with self.subTest(invalid=str(invalid)):
                online, report = normalize_runtime_extend("x", {
                    100: [{"curStageNo": 1}], 101: [{"curStageNo": invalid}],
                    102: [{"curStageNo": 2}],
                })
                self.assertEqual(online, {100: "1", 101: "-1", 102: "2"})
                self.assertEqual(report["invalid_stage_records"], 1)


if __name__ == "__main__":
    unittest.main()
