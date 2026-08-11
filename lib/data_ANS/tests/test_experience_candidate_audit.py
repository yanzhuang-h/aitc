import unittest

from lib.data_ANS.experience_candidate_audit import ExperienceCandidateAudit


class ExperienceCandidateAuditTests(unittest.TestCase):
    def test_preserves_all_samples_and_metadata(self):
        audit = ExperienceCandidateAudit()
        for index, total in enumerate((10, 12, 14)):
            audit.add_experience(
                "1300069",
                {"U": {20: [0, total]}},
                data_day="2026-06-27",
                window_start=100 + index,
                metadata={"valid_cycle_count": 3},
            )

        samples = audit.build_samples()["roads"]["1300069"]["directions"]
        self.assertEqual(len(samples["U"]["20"]), 3)
        self.assertEqual(samples["U"]["20"][2]["flow"], [0, 14])
        self.assertEqual(
            samples["U"]["20"][0]["metadata"]["valid_cycle_count"],
            3,
        )

    def test_flags_isolated_statistical_high_max(self):
        audit = ExperienceCandidateAudit(min_date_support=2)
        for index, total in enumerate((10, 10, 11, 12, 50)):
            audit.add_experience(
                "1300069",
                {"U": {20: [total]}},
                data_day="d1" if index < 3 else "d2",
                window_start=100 + index,
            )

        point = audit.build_report()["roads"]["1300069"]["directions"]["U"]["20"]
        self.assertEqual(point["sample_count"], 5)
        self.assertEqual(point["p50_total"], 11)
        self.assertEqual(point["p90_total"], 50)
        self.assertEqual(point["iqr"], 2)
        self.assertEqual(point["median_absolute_deviation"], 1.0)
        self.assertIn("isolated_dominant_max", point["flags"])
        self.assertIn("iqr_high_outlier", point["flags"])
        self.assertNotIn("low_date_support", point["flags"])

    def test_repeated_max_is_supported(self):
        audit = ExperienceCandidateAudit()
        for index, total in enumerate((10, 50, 50)):
            audit.add_experience(
                "1300070",
                {"D": {30: [total]}},
                data_day=f"d{index + 1}",
                window_start=200 + index,
            )

        point = audit.build_report()["roads"]["1300070"]["directions"]["D"]["30"]
        self.assertEqual(point["max_support_count"], 2)
        self.assertEqual(point["second_sample_total"], 50)
        self.assertNotIn("isolated_dominant_max", point["flags"])

    def test_rejects_negative_flow(self):
        audit = ExperienceCandidateAudit()
        with self.assertRaises(ValueError):
            audit.add_experience("1300069", {"U": {20: [1, -1]}})

    def test_capacity_lane_metadata_masks_unselected_flow_before_audit(self):
        audit = ExperienceCandidateAudit()

        audit.add_experience(
            "1300069",
            {"U": {20: [99, 5] + [0] * 8}},
            data_day="d1",
            metadata={"capacity_lane_indexes": [1]},
        )

        sample = audit.build_samples()["roads"]["1300069"]["directions"][
            "U"
        ]["20"][0]
        point = audit.build_report()["roads"]["1300069"]["directions"]["U"][
            "20"
        ]
        self.assertEqual(sample["flow"], [0, 5] + [0] * 8)
        self.assertEqual(point["mean_total"], 5)


if __name__ == "__main__":
    unittest.main()
