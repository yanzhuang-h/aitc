import json
from pathlib import Path
import tempfile
import unittest

from lib.data_ANS.experience_pool import run_daily_pool_update
from lib.data_ANS.experience_release import validate_experience_table
from lib.data_ANS.raw_feedback_normalizer import build_near_capacity_candidate_samples


def observation(green_time, window_start):
    return {
        "CrossId": "1700240", "direction": "U", "actual_green_time": green_time,
        "source_date": "2026-11-12", "source_window_start": window_start,
        "quality_gate_passed": True, "capacity_lane_indexes": [1],
        "candidate_observed_flow": [0, 50] + [0] * 8,
    }


class ExperienceGrowthGuardsTests(unittest.TestCase):
    def test_candidate_time_range_matches_release_bounds(self):
        candidates, stats = build_near_capacity_candidate_samples([
            observation(green, index * 600)
            for index, green in enumerate([0, 1, 150, 151, 162])
        ])
        points = candidates["roads"]["1700240"]["directions"]["U"]
        self.assertEqual(set(points), {"1", "150"})
        self.assertEqual(stats["accepted_samples"], 2)
        self.assertEqual(stats["excluded_green_time_out_of_range"], 3)

    def test_unsupported_point_cannot_block_qualified_new_direction(self):
        observations = [observation(60, index * 600) for index in range(30)]
        observations.append(observation(162, 30 * 600))
        candidates, stats = build_near_capacity_candidate_samples(observations)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, pool, old, output = [root / name for name in
                                            ["candidates.json", "pool.json", "old.json", "table.json"]]
            candidate.write_text(json.dumps(candidates))
            initial = {"1700240": {"D": {"60": [0, 100] + [0] * 8}}}
            old.write_text(json.dumps(initial))
            updated, report = run_daily_pool_update(
                str(candidate), str(pool), str(old), str(output),
                min_sample_count=30, new_point_road_ids={"1700240"},
            )
        self.assertEqual(updated["1700240"]["U"]["60"], [0, 50] + [0] * 8)
        self.assertNotIn("162", updated["1700240"]["U"])
        self.assertEqual(stats["excluded_green_time_out_of_range"], 1)
        self.assertEqual(report["accumulation"]["accepted_samples"], 30)
        cross = {"1700240": {"LaneNo": {"U": {"1": "1B"}, "D": {"1": "1B"}}}}
        self.assertTrue(validate_experience_table(updated, cross)["valid"])


if __name__ == "__main__":
    unittest.main()
