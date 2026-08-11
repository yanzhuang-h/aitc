import json
import tempfile
import unittest
from pathlib import Path

from lib.data_ANS.E_T_new import compress_phase_intervals
from lib.data_ANS.raw_data_cleaning import (
    DEFAULT_MAX_STAGE_GAP_SECONDS,
    clean_training_inputs,
)


class RawDataCleaningTests(unittest.TestCase):
    def _clean_flow(self, lane_type, movement):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flow_path = root / "flow.txt"
            extend_path = root / "extend.txt"
            flow_path.write_text(
                json.dumps({
                    "jtll_ddbh": "10",
                    "ts": 100,
                    "ycsb_cdbh": "1",
                    "ycsb_xsfx": movement,
                }) + "\n",
                encoding="utf-8",
            )
            extend_path.write_text("", encoding="utf-8")
            cross_info = {
                "x": {
                    "phase": {"1": "UD"},
                    "jtll_ddbh": {"10": "U"},
                    "LaneNo": {"U": {"1": lane_type}},
                }
            }
            flow, _, report = clean_training_inputs(
                str(flow_path),
                str(extend_path),
                cross_info,
                target_cross_ids={"x"},
            )
            return flow.get("x", []), report

    def _clean_extend(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flow_path = root / "flow.txt"
            extend_path = root / "extend.txt"
            flow_path.write_text("", encoding="utf-8")
            extend_path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            cross_info = {
                "x": {
                    "phase": {"1": "UD", "2": "LR"},
                    "jtll_ddbh": {},
                    "LaneNo": {},
                }
            }
            _, extend, report = clean_training_inputs(
                str(flow_path),
                str(extend_path),
                cross_info,
                target_cross_ids={"x"},
            )
            return extend["x"], report

    def test_direct_stage_transition_and_explicit_minus_one(self):
        extend, _ = self._clean_extend([
            {"CrossId": "x", "time": 100, "curStageNo": 1},
            {"CrossId": "x", "time": 101, "curStageNo": 2},
            {"CrossId": "x", "time": 102, "curStageNo": -1},
        ])
        self.assertEqual(extend, {100: "1", 101: "2", 102: "2"})
        intervals = compress_phase_intervals(extend)
        self.assertEqual([item["stage"] for item in intervals], ["1", "2"])
        self.assertEqual([item["duration"] for item in intervals], [1, 2])

    def test_three_missing_seconds_are_filled_but_later_seconds_are_unknown(self):
        extend, report = self._clean_extend([
            {"CrossId": "x", "time": 100, "curStageNo": 1},
            {"CrossId": "x", "time": 104, "curStageNo": 2},
            {"CrossId": "x", "time": 110, "curStageNo": 1},
        ])
        self.assertEqual(DEFAULT_MAX_STAGE_GAP_SECONDS, 3)
        self.assertEqual([extend[value] for value in (101, 102, 103)], ["1"] * 3)
        self.assertEqual([extend[value] for value in (105, 106, 107)], ["2"] * 3)
        self.assertEqual([extend[value] for value in (108, 109)], ["-1", "-1"])
        coverage = report["crosses"]["x"]["stage_coverage"]
        self.assertEqual(coverage["short_gap_filled_seconds"], 6)
        self.assertEqual(coverage["long_gap_seconds"], 2)

    def test_non_left_movement_mismatch_is_kept_and_audited(self):
        flow, report = self._clean_flow("1B", "2C")

        self.assertEqual(len(flow), 1)
        counters = report["crosses"]["x"]["flow"]
        self.assertEqual(counters["lane_movement_mismatch"], 1)
        self.assertEqual(counters["non_left_movement_mismatch_accepted"], 1)

    def test_dedicated_left_movement_mismatch_remains_rejected(self):
        flow, report = self._clean_flow("1A", "1B")

        self.assertEqual(flow, [])
        counters = report["crosses"]["x"]["flow"]
        self.assertEqual(counters["dedicated_left_movement_mismatch"], 1)


if __name__ == "__main__":
    unittest.main()
