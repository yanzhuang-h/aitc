import unittest

from lib.data_ANS import lane_policy as POLICY


class LanePolicyTests(unittest.TestCase):
    def setUp(self):
        self.cross_config = {
            "LaneNo": {
                "U": {
                    "1": "1A",
                    "2": "1B",
                    "3": "1C",
                    "4": "1D",
                    "5": "2A",
                    "6": "2B",
                    "7": "2C",
                    "8": "3A",
                    "9": "3B",
                    "0": "9Z",
                }
            }
        }

    def test_known_uncontrolled_and_unverified_types_are_not_capacity_eligible(self):
        for lane_type in ("1C", "3A", "3B", "9Z"):
            with self.subTest(lane_type=lane_type):
                self.assertFalse(
                    POLICY.classify_lane_type(lane_type)["capacity_eligible"]
                )

    def test_dedicated_left_and_controlled_base_lanes_remain_separate(self):
        base = POLICY.configured_movement_lane_policy(self.cross_config, "U")
        left = POLICY.configured_movement_lane_policy(self.cross_config, "UTL")

        self.assertEqual(base["eligible"], {2, 4, 5, 6, 7})
        self.assertEqual(set(base["excluded"]), {0, 3, 8, 9})
        self.assertEqual(left["eligible"], {1})
        self.assertEqual(left["excluded"], {})

    def test_capacity_vector_masks_every_non_capacity_lane(self):
        result = POLICY.mask_capacity_vector(
            list(range(10)),
            self.cross_config,
            "U",
        )

        self.assertEqual(result, [0, 0, 2, 0, 4, 5, 6, 7, 0, 0])


if __name__ == "__main__":
    unittest.main()
