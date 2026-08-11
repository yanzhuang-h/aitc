import unittest

from lib.data_ANS.cycle_quality import (
    MAX_ADJACENT_STAGE_CHANGE_SECONDS,
    audit_cleaned_stage_day,
    build_cycle_profile,
    compress_stage_layers,
    find_complete_cycles,
    group_consecutive_same_pattern_cycles,
)


class CycleQualityTests(unittest.TestCase):
    CONFIG = {
        "Cycle": [[1, 2], [3, 4]],
        "phase": {"1": "UD", "2": "LR", "3": "UDL", "4": "LRL"},
    }

    @staticmethod
    def _stage_map(stage_runs):
        result = {}
        timestamp = 0
        for stage, duration in stage_runs:
            for _ in range(duration):
                result[timestamp] = str(stage)
                timestamp += 1
        return result

    def _padded_stage_map(self, stage_runs):
        return self._stage_map([(9, 1)] + stage_runs + [(9, 1)])

    def test_four_directly_connected_cycles_are_all_eligible(self):
        stage_map = self._padded_stage_map([(1, 20), (2, 20)] * 4)
        samples, stats = audit_cleaned_stage_day(
            stage_map,
            self.CONFIG,
            "1300069",
            "2026-06-27",
        )

        self.assertEqual(stats["complete_cycles_found"], 4)
        self.assertEqual(stats["eligible_groups"], 1)
        self.assertEqual(stats["eligible_cycles"], 4)
        self.assertEqual(stats["complete_cycle_pattern_counts"], {"1-2": 4})
        self.assertEqual(
            stats["consecutive_run_length_counts"],
            {"1-2": {"4": 1}},
        )
        self.assertEqual(len(samples), 4)
        self.assertEqual(samples[0]["cycle_duration"], 40)
        self.assertEqual(samples[0]["group_size"], 4)
        self.assertEqual(samples[0]["cycle_index_in_group"], 0)
        self.assertEqual(samples[0]["direction_times"]["U"], 20)
        self.assertEqual(samples[0]["direction_times"]["L"], 20)

    def test_unknown_stage_layer_breaks_cycle_continuity(self):
        stage_map = self._padded_stage_map(
            [(1, 10), (2, 10)] * 2
            + [(-1, 5)]
            + [(1, 10), (2, 10)] * 2
        )
        samples, stats = audit_cleaned_stage_day(
            stage_map,
            self.CONFIG,
            "1300069",
            "2026-06-27",
        )

        self.assertEqual(stats["complete_cycles_found"], 4)
        self.assertEqual(stats["windows_without_three_consecutive_cycles"], 1)
        self.assertEqual(samples, [])

    def test_different_cycle_patterns_cannot_form_one_three_cycle_group(self):
        stage_map = self._padded_stage_map(
            [(1, 10), (2, 10)] * 2 + [(3, 10), (4, 10)] * 2
        )
        samples, stats = audit_cleaned_stage_day(
            stage_map,
            self.CONFIG,
            "1300069",
            "2026-06-27",
        )

        self.assertEqual(stats["complete_cycles_found"], 4)
        self.assertEqual(samples, [])

    def test_layer_helpers_preserve_direct_stage_transitions(self):
        stage_map = self._padded_stage_map([(1, 3), (2, 4)] * 3)
        layers = compress_stage_layers(stage_map)
        cycles = find_complete_cycles(layers, [["1", "2"]], 0, 599)
        groups = group_consecutive_same_pattern_cycles(cycles)

        self.assertEqual(
            [layer["stage"] for layer in layers],
            ["9"] + ["1", "2"] * 3 + ["9"],
        )
        self.assertEqual([len(group) for group in groups], [3])

    def test_profile_keeps_robust_duration_statistics(self):
        stage_map = self._padded_stage_map([(1, 20), (2, 20)] * 4)
        samples, _ = audit_cleaned_stage_day(
            stage_map,
            self.CONFIG,
            "1300069",
            "2026-06-27",
        )
        profile = build_cycle_profile(samples)
        pattern = profile["roads"]["1300069"]["patterns"]["1-2"]

        self.assertEqual(pattern["cycle_count"], 4)
        self.assertEqual(pattern["cycle_duration"]["median"], 40.0)
        self.assertEqual(pattern["stages"]["0"]["duration"]["p95"], 20)
        changes = pattern["adjacent_cycle_changes"]
        self.assertEqual(changes["group_count"], 1)
        self.assertEqual(changes["comparison_count"], 3)
        self.assertEqual(changes["stages"]["0"]["p95"], 0)
        self.assertEqual(
            changes["stages"]["0"]["suggested_max_delta_seconds"],
            5,
        )
        self.assertEqual(
            changes["stages"]["0"]["suggested_robust_max_delta_seconds"],
            5,
        )
        self.assertEqual(
            changes["stages"]["0"]["configured_max_delta_seconds"],
            8,
        )
        self.assertEqual(
            changes["within_group_ranges"]["stages"]["0"]["p95"],
            0,
        )
        self.assertFalse(profile["candidate_ranges_are_enforced"])

    def test_adjacent_stage_change_limit_is_uniform_eight_seconds(self):
        self.assertEqual(MAX_ADJACENT_STAGE_CHANGE_SECONDS, 8)
        accepted_map = self._padded_stage_map([
            (1, 10), (2, 10),
            (1, 10), (2, 10),
            (1, 18), (2, 10),
        ])
        rejected_map = self._padded_stage_map([
            (1, 10), (2, 10),
            (1, 10), (2, 10),
            (1, 19), (2, 10),
        ])

        accepted, accepted_stats = audit_cleaned_stage_day(
            accepted_map,
            self.CONFIG,
            "1300069",
            "2026-06-27",
        )
        rejected, rejected_stats = audit_cleaned_stage_day(
            rejected_map,
            self.CONFIG,
            "1300069",
            "2026-06-27",
        )

        self.assertEqual(len(accepted), 3)
        self.assertEqual(accepted_stats.get("stage_change_breaks", 0), 0)
        self.assertEqual(rejected, [])
        self.assertEqual(rejected_stats["stage_change_breaks"], 1)
        self.assertEqual(
            rejected_stats["windows_without_three_consistent_cycles"],
            1,
        )

    def test_first_and_last_data_layers_are_not_complete_cycle_stages(self):
        stage_map = self._stage_map([(1, 10), (2, 10)] * 3)
        samples, stats = audit_cleaned_stage_day(
            stage_map,
            self.CONFIG,
            "1300069",
            "2026-06-27",
        )

        self.assertEqual(stats["complete_cycles_found"], 1)
        self.assertEqual(samples, [])

    def test_long_cycles_use_centered_fifteen_minute_observation(self):
        stage_map = self._padded_stage_map(
            [(1, 100), (2, 130)] * 3
        )
        samples, stats = audit_cleaned_stage_day(
            stage_map,
            self.CONFIG,
            "1300070",
            "2026-06-27",
        )

        self.assertEqual(len(samples), 3)
        self.assertEqual(stats["expanded_observation_eligible_windows"], 1)
        self.assertTrue(samples[0]["cycle_observation_expanded"])
        self.assertEqual(samples[0]["flow_window_seconds"], 600)
        self.assertEqual(samples[0]["cycle_observation_seconds"], 900)
        self.assertEqual(samples[0]["cycle_duration"], 230)

    def test_two_hundred_second_cycles_keep_ten_minute_observation(self):
        stage_map = self._padded_stage_map(
            [(1, 90), (2, 110)] * 3
        )
        samples, stats = audit_cleaned_stage_day(
            stage_map,
            self.CONFIG,
            "1300070",
            "2026-06-27",
        )

        self.assertEqual(samples, [])
        self.assertEqual(stats.get("expanded_observation_attempts", 0), 0)
        self.assertEqual(
            stats["cycle_observation_decision_cycle_not_over_threshold"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
