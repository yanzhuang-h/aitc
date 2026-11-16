import unittest

from lib.control_functions.global_processors.phase_adapter import allocate_phase_times
from lib.data_ANS.flow_time_allocator import allocate_from_runtime_data
from lib.data_ANS.raw_feedback_normalizer import _direction_green_times, _movement_green_runs


class SharedPhaseDefinitionsTests(unittest.TestCase):
    def test_training_aliases_preserve_green_times_and_release_intervals(self):
        cycles = [{"start": 100, "end": 139, "items": [
            {"stage": "1", "start": 100, "end": 119, "duration": 20},
            {"stage": "2", "start": 120, "end": 139, "duration": 20},
        ]}]
        for canonical, alias in [("UD", "DU"), ("LR", "RL"), ("UDL", "DUL"),
                                 ("UD", "UD1"), ("UD", "UD2"), ("LR", "LR1"), ("LR", "LR2")]:
            with self.subTest(alias=alias):
                baseline = {"phase": {"1": canonical, "2": "P"}}
                changed = {"phase": {"1": alias, "2": "P"}}
                self.assertEqual(_direction_green_times(cycles, baseline),
                                 _direction_green_times(cycles, changed))
                for direction in ["U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL"]:
                    self.assertEqual(_movement_green_runs(cycles, baseline, direction),
                                     _movement_green_runs(cycles, changed, direction))

    def test_runtime_stage_evidence_activates_canonical_and_alias_movements_equally(self):
        for canonical, alias in [("UD", "DU"), ("LR", "RL"), ("UDL", "DUL"),
                                 ("UD", "UD1"), ("LR", "LR2")]:
            with self.subTest(alias=alias):
                results = []
                for phase in [canonical, alias]:
                    results.append(allocate_from_runtime_data(
                        "x", {}, {1000: [{"CrossId": "x", "curStageNo": "1"}]},
                        experience_table={"x": {}},
                        cross_info={"x": {"phase": {"1": phase}, "LaneNo": {
                            d: {"1": "1B", "2": "1A"} for d in ["U", "D", "L", "R"]
                        }}},
                    ))
                self.assertEqual(results[0]["time_vector"], results[1]["time_vector"])
                self.assertEqual(results[0]["active_directions"], results[1]["active_directions"])
                self.assertTrue(results[0]["active_directions"])

    def test_phase_aliases_preserve_final_bounded_phase_allocation(self):
        for canonical, alias in [("UD", "DU"), ("LR", "RL"), ("UDL", "DUL")]:
            with self.subTest(alias=alias):
                def config(phase):
                    return {"phase": [phase, "P"], "min_pass_time": [15, 10],
                            "max_pass_time": [100, 30]}
                demand = {"U": 45, "D": 30, "L": 50, "R": 20, "UTL": 25, "DTL": 35}
                baseline, _ = allocate_phase_times(demand, config(canonical))
                actual, _ = allocate_phase_times(demand, config(alias))
                self.assertEqual(actual, baseline)
                self.assertGreaterEqual(sum(actual), 60)


if __name__ == "__main__":
    unittest.main()
