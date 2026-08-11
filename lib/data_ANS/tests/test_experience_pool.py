import json
import tempfile
import unittest
from pathlib import Path

from lib.data_ANS.experience_pool import (
    ExperiencePool,
    blend_eligible_lane_updates,
    blend_experience_tables,
    densest_cluster_median,
    nearest_rank_percentile,
    select_pool_lane_value,
    select_audit_gated_table,
    run_daily_pool_update,
)


def _candidate(date, value, window_start):
    return {
        "roads": {
            "1300069": {
                "directions": {
                    "U": {
                        "60": [
                            {
                                "date": date,
                                "window_start": window_start,
                                "flow": [0, value, value + 1, 0, 0, 0, 0, 0, 0, 0],
                                "metadata": {"valid_cycle_count": 3},
                            }
                        ]
                    }
                }
            }
        }
    }


class ExperiencePoolTests(unittest.TestCase):
    def test_nearest_rank_eightieth_percentile(self):
        self.assertEqual(nearest_rank_percentile(range(1, 11), 0.8), 8)
        self.assertEqual(
            nearest_rank_percentile([1, 1, 1, 1, 5, 6, 7, 8, 9, 10], 0.8),
            8,
        )

    def test_densest_cluster_median_flattens_low_and_high_groups(self):
        values = (
            [8, 9, 10]
            + [48, 49, 50, 50, 50, 51] * 3
            + [90, 95, 100, 105, 110, 115, 120, 125, 130]
        )

        selected, report = densest_cluster_median(values)

        self.assertEqual(len(values), 30)
        self.assertEqual(selected, 50)
        self.assertEqual(report["cluster_size"], 15)
        self.assertEqual(report["cluster_lower"], 48)
        self.assertEqual(report["cluster_upper"], 50)
        self.assertEqual(report["cluster_width"], 2)
        self.assertEqual(report["outside_cluster_count"], 15)

        _, selection_report = select_pool_lane_value(values)
        self.assertEqual(selection_report["selected_value"], 50)
        self.assertEqual(selection_report["p80_reference_value"], 100)

    def test_densest_cluster_tie_prefers_higher_capacity_group(self):
        selected, report = densest_cluster_median([10] * 15 + [20] * 15)

        self.assertEqual(selected, 20)
        self.assertEqual(report["cluster_lower"], 20)
        self.assertEqual(report["cluster_upper"], 20)

    def test_pool_selector_can_still_use_p80_for_comparison(self):
        selected, report = select_pool_lane_value(
            list(range(1, 11)),
            selection_method="p80",
        )

        self.assertEqual(selected, 8)
        self.assertEqual(report["selection_method"], "p80")

    def test_lane_pool_and_compression(self):
        pool = ExperiencePool()
        samples = _candidate("d1", 1, 100)
        samples["roads"]["1300069"]["directions"]["U"]["60"].extend(
            _candidate("d1", 2, 200)["roads"]["1300069"]["directions"]["U"]["60"]
        )
        samples["roads"]["1300069"]["directions"]["U"]["60"].extend(
            _candidate("d1", 9, 300)["roads"]["1300069"]["directions"]["U"]["60"]
        )
        stats = pool.add_candidate_samples(samples)
        self.assertEqual(stats["accepted_samples"], 3)
        full = pool.build_full_pool()
        self.assertEqual(
            len(full["roads"]["1300069"]["U"]["60"]["1"]),
            3,
        )
        table, report = pool.compress(percentile=0.8)
        self.assertEqual(table["1300069"]["U"]["60"][1], 9)
        self.assertEqual(table["1300069"]["U"]["60"][2], 10)
        self.assertEqual(
            report["roads"]["1300069"]["summary"]["candidate_samples"],
            3,
        )

        duplicate_stats = pool.add_candidate_samples(samples)
        self.assertEqual(duplicate_stats["accepted_samples"], 0)
        self.assertEqual(duplicate_stats["duplicate_samples"], 3)

    def test_capacity_lane_mask_does_not_add_zero_records_for_other_lanes(self):
        pool = ExperiencePool()
        sample = _candidate("d1", 12, 100)
        sample["roads"]["1300069"]["directions"]["U"]["60"][0][
            "flow"
        ] = [99, 12] + [0] * 8
        sample["roads"]["1300069"]["directions"]["U"]["60"][0][
            "metadata"
        ]["capacity_lane_indexes"] = [1]

        stats = pool.add_candidate_samples(sample)

        self.assertEqual(stats["accepted_samples"], 1)
        self.assertEqual(stats["lane_records_added"], 1)
        self.assertEqual(stats["masked_lane_records"], 9)
        lane_map = pool.build_full_pool()["roads"]["1300069"]["U"]["60"]
        self.assertNotIn("0", lane_map)
        self.assertEqual(lane_map["1"][0]["flow"], 12)

    def test_blend_preserves_missing_points(self):
        old = {
            "1300069": {
                "U": {"60": [10, 20, 0, 0, 0, 0, 0, 0, 0, 0]},
                "D": {"40": [3, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
            }
        }
        new = {
            "1300069": {
                "U": {
                    "60": [20, 10, 0, 0, 0, 0, 0, 0, 0, 0],
                    "70": [8, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                }
            }
        }
        result, report = blend_experience_tables(old, new)
        self.assertEqual(result["1300069"]["U"]["60"][:2], [12, 18])
        self.assertEqual(result["1300069"]["U"]["70"][0], 8)
        self.assertEqual(result["1300069"]["D"]["40"][0], 3)
        self.assertEqual(report["points_blended"], 1)
        self.assertEqual(report["new_points_added"], 1)
        self.assertEqual(report["old_points_preserved"], 1)

    def test_audit_gated_selection_uses_p80_and_skips_low_support(self):
        samples = {
            "roads": {
                "1300069": {
                    "directions": {
                        "U": {
                            "60": [
                                {
                                    "date": "d1" if value < 12 else "d2",
                                    "window_start": value,
                                    "flow": [value] + [0] * 9,
                                }
                                for value in (10, 10, 11, 12, 50)
                            ],
                            "61": [
                                {
                                    "date": "d1",
                                    "window_start": 1,
                                    "flow": [10] + [0] * 9,
                                },
                                {
                                    "date": "d2",
                                    "window_start": 2,
                                    "flow": [11] + [0] * 9,
                                },
                            ],
                        }
                    }
                }
            }
        }
        audit = {
            "roads": {
                "1300069": {
                    "directions": {
                        "U": {
                            "60": {
                                "sample_count": 5,
                                "dates": ["d1", "d2"],
                                "flags": [
                                    "isolated_dominant_max",
                                    "iqr_high_outlier",
                                ],
                            },
                            "61": {
                                "sample_count": 2,
                                "dates": ["d1", "d2"],
                                "flags": ["low_support"],
                            },
                        }
                    }
                }
            }
        }

        table, report = select_audit_gated_table(samples, audit)

        self.assertEqual(table["1300069"]["U"]["60"][0], 12)
        self.assertNotIn("61", table["1300069"]["U"])
        point = report["roads"]["1300069"]["directions"]["U"]["60"]
        self.assertEqual(
            point["decision"],
            "accepted_p80_replacing_isolated_outlier",
        )
        self.assertEqual(report["summary"]["rejected_insufficient_samples"], 1)

    def test_audit_gated_selection_ignores_unselected_lane_zeros(self):
        samples = {
            "roads": {
                "1300069": {
                    "directions": {
                        "U": {
                            "60": [
                                {
                                    "date": "d1" if value < 12 else "d2",
                                    "window_start": value,
                                    "flow": [99, value] + [0] * 8,
                                    "metadata": {
                                        "capacity_lane_indexes": [1]
                                    },
                                }
                                for value in (10, 10, 11, 12, 50)
                            ]
                        }
                    }
                }
            }
        }
        audit = {
            "roads": {
                "1300069": {
                    "directions": {
                        "U": {
                            "60": {
                                "sample_count": 5,
                                "dates": ["d1", "d2"],
                                "flags": [],
                            }
                        }
                    }
                }
            }
        }

        table, _ = select_audit_gated_table(samples, audit)

        self.assertEqual(table["1300069"]["U"]["60"], [0, 12] + [0] * 8)

    def test_daily_updates_are_chronological_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path = root / "candidate.json"
            full_pool_path = root / "full_pool.json"
            old_path = root / "old.json"
            output_path = root / "table.json"
            candidate = _candidate("d1", 10, 100)
            candidate["roads"]["1300069"]["directions"]["U"]["60"].append(
                _candidate("d2", 20, 200)["roads"]["1300069"]["directions"]["U"]["60"][0]
            )
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            old_path.write_text(
                json.dumps({
                    "1300069": {
                        "U": {"60": [0] * 10}
                    }
                }),
                encoding="utf-8",
            )

            result, report = run_daily_pool_update(
                str(candidate_path),
                str(full_pool_path),
                str(old_path),
                str(output_path),
                min_sample_count=1,
            )
            self.assertEqual(result["1300069"]["U"]["60"][1], 6)
            self.assertEqual(
                report["days"]["d1"]["status"],
                "pool_updated_table_updated",
            )
            self.assertEqual(
                report["days"]["d2"]["status"],
                "pool_updated_table_updated",
            )

            output_path.unlink()
            rerun_result, rerun_report = run_daily_pool_update(
                str(candidate_path),
                str(full_pool_path),
                str(old_path),
                str(output_path),
                min_sample_count=1,
            )
            self.assertEqual(rerun_result, result)
            self.assertTrue(output_path.exists())
            self.assertIn("#state.rolling_table", rerun_report["effective_old_table_path"])
            self.assertEqual(rerun_report["days"]["d1"]["status"], "already_applied")
            self.assertEqual(rerun_report["days"]["d2"]["status"], "already_applied")

    def test_collection_only_road_is_stored_but_cannot_change_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path = root / "candidate.json"
            full_pool_path = root / "full_pool.json"
            old_path = root / "old.json"
            output_path = root / "table.json"
            candidate = _candidate("2026-07-24", 20, 100)
            candidate["roads"]["1300086"] = {
                "directions": {
                    "U": {
                        "60": _candidate(
                            "2026-07-24",
                            50,
                            100,
                        )["roads"]["1300069"]["directions"]["U"]["60"]
                    }
                }
            }
            old_table = {
                road_id: {"U": {"60": [0, 10, 11] + [0] * 7}}
                for road_id in ("1300069", "1300086")
            }
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            old_path.write_text(json.dumps(old_table), encoding="utf-8")

            result, report = run_daily_pool_update(
                str(candidate_path),
                str(full_pool_path),
                str(old_path),
                str(output_path),
                min_sample_count=1,
                update_road_ids={"1300069"},
            )

            self.assertNotEqual(result["1300069"], old_table["1300069"])
            self.assertEqual(result["1300086"], old_table["1300086"])
            pool = json.loads(full_pool_path.read_text(encoding="utf-8"))
            self.assertIn("1300069", pool["roads"])
            self.assertIn("1300086", pool["roads"])
            day_report = report["days"]["2026-07-24"]
            self.assertGreater(day_report["update_withheld_lane_cells"], 0)
            self.assertEqual(report["update_road_ids"], ["1300069"])

    def test_cumulative_threshold_updates_only_eligible_lane(self):
        pool = ExperiencePool()
        samples = {
            "roads": {
                "1": {
                    "directions": {
                        "U": {
                            "60": [
                                {
                                    "date": "2026-07-24",
                                    "window_start": index * 600,
                                    "source_id": f"sample-{index}",
                                    "flow": [0, 40 + index, 80 + index] + [0] * 7,
                                    "metadata": {
                                        "capacity_lane_indexes": (
                                            [1, 2] if index < 29 else [1]
                                        )
                                    },
                                }
                                for index in range(30)
                            ]
                        }
                    }
                }
            }
        }
        pool.add_candidate_samples(samples)
        table2, masks, report = pool.compress_eligible_lane_updates(
            {
                ("1", "U", "60", 1),
                ("1", "U", "60", 2),
            },
            min_sample_count=30,
        )

        self.assertEqual(masks["1"]["U"]["60"], [1])
        self.assertGreater(table2["1"]["U"]["60"][1], 0)
        self.assertEqual(report["summary"]["eligible_lane_cells"], 1)
        self.assertEqual(report["summary"]["insufficient_lane_cells"], 1)
        self.assertEqual(report["selection_method"], "densest_cluster_median")
        lane_report = report["lane_cells"]["1/U/60/1"]
        self.assertEqual(
            lane_report["decision"],
            "eligible_cumulative_densest_cluster",
        )
        self.assertEqual(
            lane_report["selection_details"]["cluster_size"],
            15,
        )

        old = {"1": {"U": {"60": [0, 20, 70] + [0] * 7}}}
        blended, blend_report = blend_eligible_lane_updates(old, table2, masks)
        self.assertNotEqual(blended["1"]["U"]["60"][1], 20)
        self.assertEqual(blended["1"]["U"]["60"][2], 70)
        self.assertEqual(blend_report["lane_values_blended"], 1)

    def test_eligible_blend_does_not_create_missing_time_point(self):
        old = {"1": {"U": {"60": [0, 20] + [0] * 8}}}
        table2 = {"1": {"U": {"61": [0, 40] + [0] * 8}}}
        masks = {"1": {"U": {"61": [1]}}}

        blended, report = blend_eligible_lane_updates(old, table2, masks)

        self.assertNotIn("61", blended["1"]["U"])
        self.assertEqual(blended, old)
        self.assertEqual(report["missing_old_or_p80_points"], 1)


if __name__ == "__main__":
    unittest.main()
