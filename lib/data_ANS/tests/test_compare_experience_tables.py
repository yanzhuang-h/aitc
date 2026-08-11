import io
import unittest

from lib.data_ANS import compare_experience_tables as COMPARE


class CompareExperienceTablesTests(unittest.TestCase):
    def setUp(self):
        self.cross_info = {
            "test": {
                "LaneNo": {
                    "U": {
                        "1": "1A",
                        "2": "1B",
                        "3": "1C",
                        "4": "2A",
                        "5": "1A",
                    }
                }
            }
        }
        self.vector = [0, 10, 20, 30, 40, 50, 0, 0, 0, 0]

    def test_base_sum_excludes_left_and_uncontrolled_lanes(self):
        lanes = COMPARE.movement_lane_details(
            self.cross_info,
            "test",
            "U",
        )

        self.assertEqual([item["lane"] for item in lanes], [2, 4])
        self.assertEqual(COMPARE.movement_total(self.vector, lanes), 60)

    def test_left_sum_includes_all_1a_lanes(self):
        lanes = COMPARE.movement_lane_details(
            self.cross_info,
            "test",
            "UTL",
        )

        self.assertEqual([item["lane"] for item in lanes], [1, 5])
        self.assertEqual(COMPARE.movement_total(self.vector, lanes), 60)

    def test_output_uses_dash_for_missing_time_instead_of_zero(self):
        output = io.StringIO()
        COMPARE.print_direction_compare(
            "test",
            "U",
            {"U": {"30": self.vector}},
            {"U": {"31": self.vector}},
            self.cross_info,
            "raw",
            "completed",
            output,
        )

        text = output.getvalue()
        self.assertIn("2(1B), 4(2A)", text)
        self.assertIn("    30", text)
        self.assertIn("-", text)


if __name__ == "__main__":
    unittest.main()
