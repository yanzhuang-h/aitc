import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "buqi_new2.0.py"
SPEC = importlib.util.spec_from_file_location("buqi_new2_0", MODULE_PATH)
BUQI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUQI)


class BuqiValidRangeTests(unittest.TestCase):
    @staticmethod
    def _flow(value):
        return [value] + [0] * 9

    def test_missing_time_points_do_not_become_zero_flow(self):
        series = {
            "41": self._flow(10),
            "47": self._flow(10),
            "48": self._flow(10),
            "49": self._flow(10),
            "50": self._flow(10),
            "51": self._flow(10),
            "52": self._flow(10),
        }

        start, end, info = BUQI.get_valid_time_range_from_series(
            series,
            BUQI.sum_flow,
        )

        self.assertEqual((start, end), (41, 52))
        self.assertEqual(info["missing_time_count"], 5)
        self.assertEqual(info["max_observed_gap_seconds"], 5)
        self.assertFalse(info["missing_time_as_zero"])

    def test_observed_consecutive_zero_points_still_cut_range(self):
        series = {
            str(time): self._flow(10 if time < 47 else 0)
            for time in range(41, 53)
        }

        start, end, info = BUQI.get_valid_time_range_from_series(
            series,
            BUQI.sum_flow,
        )

        self.assertEqual((start, end), (41, 46))
        self.assertEqual(info["zero_start_time"], 47)
        self.assertEqual(info["zero_trigger_time"], 52)
        self.assertEqual(info["missing_time_count"], 0)

    def test_time_zero_only_input_is_not_a_valid_direction(self):
        start, end, info = BUQI.get_valid_time_range_from_series(
            {"0": self._flow(0)},
            BUQI.sum_flow,
        )

        self.assertIsNone(start)
        self.assertIsNone(end)
        self.assertEqual(info["reason"], "no_items_after_time_filter")

    def test_section_ratios_follow_time_not_sparse_point_order(self):
        result = BUQI.apply_time_section_ratios(
            {"1": 100, "10": 100, "20": 100, "100": 100},
            section_ratios=[1.0, 0.8, 0.6, 0.4],
        )

        self.assertEqual(result[1], 100)
        self.assertEqual(result[10], 100)
        self.assertEqual(result[20], 100)
        self.assertEqual(result[100], 40)

    def test_default_fill_preserves_trusted_points(self):
        result, info = BUQI.build_clean_fill_map_from_series(
            times=[10, 12],
            vals=[100, 50],
        )

        self.assertEqual(result, {10: 100, 11: 75, 12: 50})
        self.assertEqual(info["mode"], "preserve_trusted_points_interpolation")
        self.assertEqual(info["monotonic_conflict_count"], 1)

    def test_isotonic_fill_makes_capacity_non_decreasing(self):
        result, info = BUQI.build_isotonic_fill_values(
            all_times=[10, 11, 12, 13],
            trusted_times=[10, 12, 13],
            trusted_vals=[10, 30, 20],
            max_allowed_value=30,
        )

        self.assertEqual(result, {10: 10, 11: 18, 12: 25, 13: 25})
        self.assertEqual(info["mode"], "monotone_isotonic_interpolation")
        self.assertEqual(info["monotonic_conflict_count"], 1)
        self.assertEqual(info["adjusted_trusted_point_count"], 2)
        self.assertEqual(
            list(result.values()),
            sorted(result.values()),
        )

    def test_completion_report_records_only_added_time(self):
        source = {"test": {"U": {"10": self._flow(10)}}}
        completed = {
            "test": {
                "U": {
                    "10": self._flow(10),
                    "11": self._flow(11),
                }
            }
        }

        report = BUQI.build_completion_report(source, completed)

        self.assertEqual(report["summary"]["source_points"], 1)
        self.assertEqual(report["summary"]["completed_points"], 2)
        self.assertEqual(report["summary"]["added_points"], 1)
        self.assertEqual(report["summary"]["changed_source_points"], 0)
        self.assertEqual(
            report["roads"]["test"]["directions"]["U"]["added_time_points"],
            ["11"],
        )

    def test_missing_1a_left_direction_is_removed(self):
        road_data = {"UTL": {"20": self._flow(0)}}
        cross_info = {"test": {"LaneNo": {"U": {"1": "1B"}}}}

        result = BUQI.complete_one_left_turn_direction(
            road_data,
            cross_info,
            "test",
            "UTL",
        )

        self.assertNotIn("UTL", result)

    def test_base_completion_uses_only_controlled_base_lanes(self):
        road_data = {
            "U": {
                "10": [0, 90, 20, 80] + [0] * 6,
                "12": [0, 70, 30, 60] + [0] * 6,
            }
        }
        cross_info = {
            "test": {
                "LaneNo": {
                    "U": {"1": "1A", "2": "1B", "3": "1C"},
                }
            }
        }

        result = BUQI.complete_one_base_direction(
            road_data,
            "U",
            cross_info=cross_info,
            road_id="test",
        )

        self.assertEqual(sorted(result["U"]), ["10", "11", "12"])
        self.assertEqual(result["U"]["10"], [0, 0, 20] + [0] * 7)
        self.assertEqual(result["U"]["12"], [0, 0, 30] + [0] * 7)

    def test_base_direction_without_controlled_lanes_is_removed(self):
        road_data = {"U": {"10": [0, 30] + [0] * 8}}
        cross_info = {"test": {"LaneNo": {"U": {"1": "3A"}}}}

        result = BUQI.complete_one_base_direction(
            road_data,
            "U",
            cross_info=cross_info,
            road_id="test",
        )

        self.assertNotIn("U", result)


if __name__ == "__main__":
    unittest.main()
