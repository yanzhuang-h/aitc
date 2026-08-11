import unittest

from lib.data_ANS import E_T_new


class ETNewCycleGateTests(unittest.TestCase):
    @staticmethod
    def _stage_map(stage_runs):
        result = {}
        timestamp = 0
        for stage, duration in stage_runs:
            for _ in range(duration):
                result[timestamp] = str(stage)
                timestamp += 1
        return result

    def _find(self, stage_runs, patterns):
        stage_map = self._stage_map([(9, 1)] + stage_runs + [(9, 1)])
        intervals = E_T_new.compress_phase_intervals(stage_map)
        return E_T_new.find_complete_cycles_from_intervals(
            intervals,
            patterns,
            0,
            599,
        )

    def test_training_excludes_raw_only_lane_types_from_experience_vectors(self):
        cross_info = {
            "test": {
                "jtll_ddbh": {"det": "U"},
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
                    }
                },
            }
        }
        flow = [
            {"jtll_ddbh": "det", "lan": lane}
            for lane in range(1, 10)
        ]

        vectors, stats = E_T_new.split_flow_by_movement(
            flow,
            "test",
            cross_info,
        )

        self.assertEqual(vectors["UTL"][1], 1)
        self.assertEqual(vectors["U"][2], 1)
        self.assertEqual(
            [index for index, value in enumerate(vectors["U"]) if value],
            [2, 4, 5, 6, 7],
        )
        self.assertEqual(vectors["U"][3], 0)
        self.assertEqual(vectors["U"][8:10], [0, 0])
        self.assertEqual(stats["accepted_records"], 6)
        self.assertEqual(stats["excluded_non_capacity_records"], 3)
        self.assertEqual(stats["excluded_uncontrolled_records"], 2)
        self.assertEqual(stats["excluded_unverified_records"], 1)

    def test_different_patterns_cannot_be_combined_to_reach_three_cycles(self):
        cycles = self._find(
            [(1, 10), (2, 10)] * 2 + [(3, 10), (4, 10)],
            [["1", "2"], ["3", "4"]],
        )
        selected, audit = E_T_new.select_consistent_cycle_group(cycles)

        self.assertEqual(len(cycles), 3)
        self.assertEqual(selected, [])
        self.assertEqual(audit["consecutive_pattern_group_sizes"], [2, 1])
        self.assertEqual(audit["structural_group_count"], 0)

    def test_eight_second_change_and_short_stable_stage_are_accepted(self):
        cycles = self._find(
            [
                (1, 10), (2, 13),
                (1, 10), (2, 13),
                (1, 18), (2, 13),
            ],
            [["1", "2"]],
        )
        selected, audit = E_T_new.select_consistent_cycle_group(cycles)

        self.assertEqual(len(selected), 3)
        self.assertEqual(audit["stage_change_break_count"], 0)
        self.assertEqual(audit["stage_change_limit_seconds"], 8)

    def test_nine_second_change_breaks_the_training_group(self):
        cycles = self._find(
            [
                (1, 10), (2, 13),
                (1, 10), (2, 13),
                (1, 19), (2, 13),
            ],
            [["1", "2"]],
        )
        selected, audit = E_T_new.select_consistent_cycle_group(cycles)

        self.assertEqual(selected, [])
        self.assertEqual(audit["stage_change_break_count"], 1)
        self.assertEqual(audit["consistent_group_count"], 0)

    def test_file_boundary_partial_layers_are_not_complete_cycles(self):
        stage_map = self._stage_map([(1, 10), (2, 10)] * 3)
        intervals = E_T_new.compress_phase_intervals(stage_map)
        cycles = E_T_new.find_complete_cycles_from_intervals(
            intervals,
            [["1", "2"]],
            0,
            599,
        )

        self.assertEqual(len(cycles), 1)

    def test_jiagong_no_longer_rejects_stable_thirteen_second_stages(self):
        road_id = "cycle-gate-test"
        original = E_T_new.lines3.get(road_id)
        E_T_new.lines3[road_id] = {
            "Cycle": [[1, 2]],
            "phase": {"1": "UD", "2": "LR"},
            "jtll_ddbh": {"det": "U"},
            "LaneNo": {"U": {"1": "1B"}},
        }
        try:
            stage_map = self._stage_map(
                [(9, 1)] + [(1, 13), (2, 13)] * 3 + [(9, 1)]
            )
            result = E_T_new.jiagong(
                flow=[{"time": 1, "jtll_ddbh": "det", "lan": 1}],
                phase_intervals=E_T_new.compress_phase_intervals(stage_map),
                road_id=road_id,
                diyici=1,
                window_start=0,
                window_end=599,
            )
        finally:
            if original is None:
                E_T_new.lines3.pop(road_id, None)
            else:
                E_T_new.lines3[road_id] = original

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["cycles"], 3)
        self.assertEqual(result["cycle_gate"]["selected_pattern"], ["1", "2"])
        self.assertIn(13, result["experience"]["U"])
        self.assertNotIn("UTL", result["experience"])
        self.assertIn("UTL", result["excluded_left_turn_directions"])

    def test_left_turn_requires_1a_lane_and_releasing_phase(self):
        road_id = "left-turn-direction-gate-test"
        original = E_T_new.lines3.get(road_id)
        E_T_new.lines3[road_id] = {
            "Cycle": [[1, 2]],
            "phase": {"1": "U", "2": "LR"},
            "jtll_ddbh": {"det": "U"},
            "LaneNo": {"U": {"1": "1A"}},
        }
        try:
            stage_map = self._stage_map(
                [(9, 1)] + [(1, 13), (2, 13)] * 3 + [(9, 1)]
            )
            result = E_T_new.jiagong(
                flow=[{"time": 1, "jtll_ddbh": "det", "lan": 1}],
                phase_intervals=E_T_new.compress_phase_intervals(stage_map),
                road_id=road_id,
                diyici=1,
                window_start=0,
                window_end=599,
            )
        finally:
            if original is None:
                E_T_new.lines3.pop(road_id, None)
            else:
                E_T_new.lines3[road_id] = original

        self.assertEqual(result["status"], "accepted")
        self.assertIn("UTL", result["experience"])
        self.assertNotIn("UTL", result["excluded_left_turn_directions"])

    def test_left_turn_release_stage_must_belong_to_cycle(self):
        road_id = "inactive-left-turn-stage-test"
        cross_info = {
            road_id: {
                "Cycle": [[1, 2]],
                "phase": {"1": "UD", "2": "LR", "3": "U"},
                "LaneNo": {"U": {"1": "1A"}},
            }
        }

        supported = E_T_new.supported_dedicated_left_directions(
            road_id,
            cross_info,
        )

        self.assertNotIn("UTL", supported)

    def test_jiagong_expands_only_cycle_observation_to_fifteen_minutes(self):
        road_id = "long-cycle-gate-test"
        original = E_T_new.lines3.get(road_id)
        E_T_new.lines3[road_id] = {
            "Cycle": [[1, 2]],
            "phase": {"1": "UD", "2": "LR"},
            "jtll_ddbh": {"det": "U"},
            "LaneNo": {"U": {"1": "1B"}},
        }
        try:
            stage_map = self._stage_map(
                [(9, 1)] + [(1, 100), (2, 111)] * 4 + [(9, 1)]
            )
            result = E_T_new.jiagong(
                flow=[{"time": 100, "jtll_ddbh": "det", "lan": 1}],
                phase_intervals=E_T_new.compress_phase_intervals(stage_map),
                road_id=road_id,
                diyici=1,
                window_start=100,
                window_end=699,
            )
        finally:
            if original is None:
                E_T_new.lines3.pop(road_id, None)
            else:
                E_T_new.lines3[road_id] = original

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["cycles"], 3)
        observation = result["cycle_observation"]
        self.assertEqual(observation["flow_window_seconds"], 600)
        self.assertEqual(observation["initial_complete_cycle_count"], 2)
        self.assertEqual(observation["cycle_observation_seconds"], 900)
        self.assertTrue(observation["expanded"])
        decision = observation["expansion_decision"]
        self.assertEqual(decision["reason"], "long_cycle_over_threshold")
        self.assertGreater(
            decision["representative_cycle_duration_seconds"],
            200,
        )
        self.assertIn(100, result["experience"]["U"])

    def test_two_hundred_second_cycles_do_not_expand_observation(self):
        road_id = "threshold-cycle-gate-test"
        original = E_T_new.lines3.get(road_id)
        E_T_new.lines3[road_id] = {
            "Cycle": [[1, 2]],
            "phase": {"1": "UD", "2": "LR"},
            "jtll_ddbh": {"det": "U"},
            "LaneNo": {"U": {"1": "1B"}},
        }
        try:
            stage_map = self._stage_map(
                [(9, 1)] + [(1, 90), (2, 110)] * 3 + [(9, 1)]
            )
            result = E_T_new.jiagong(
                flow=[{"time": 100, "jtll_ddbh": "det", "lan": 1}],
                phase_intervals=E_T_new.compress_phase_intervals(stage_map),
                road_id=road_id,
                diyici=1,
                window_start=100,
                window_end=699,
            )
        finally:
            if original is None:
                E_T_new.lines3.pop(road_id, None)
            else:
                E_T_new.lines3[road_id] = original

        self.assertEqual(result["status"], "fewer_than_three_cycles")
        observation = result["cycle_observation"]
        self.assertFalse(observation["expanded"])
        self.assertEqual(observation["cycle_observation_seconds"], 600)
        decision = observation["expansion_decision"]
        self.assertEqual(decision["reason"], "cycle_not_over_threshold")
        self.assertEqual(
            decision["representative_cycle_duration_seconds"],
            200,
        )


if __name__ == "__main__":
    unittest.main()
