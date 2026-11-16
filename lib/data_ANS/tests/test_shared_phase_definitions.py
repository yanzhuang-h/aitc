"""用明确方向和秒数校验在线、离线与配时的共同相位语义。"""
import unittest

from lib.control_functions.global_processors.phase_adapter import allocate_phase_times
from lib.data_ANS.flow_time_allocator import allocate_from_runtime_data
from lib.data_ANS.raw_feedback_normalizer import _direction_green_times, _movement_green_runs
from offline_tools.offline_trainer.capacity_estimator import calc_direction_time_from_cycles

DIRECTIONS = ("U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL")
CASES = [
    (("UD", "DU", "UD1", "UD2"), {"U", "D"}),
    (("LR", "RL", "LR1", "LR2"), {"L", "R"}),
    (("UDL", "DUL"), {"UTL", "DTL"}),
    (("LRL",), {"LTL", "RTL"}),
    (("U",), {"U", "UTL"}), (("D",), {"D", "DTL"}),
    (("L",), {"L", "LTL"}), (("R",), {"R", "RTL"}),
    (("LTD",), {"LTL", "D"}), (("P",), set()),
]


class SharedPhaseDefinitionsTests(unittest.TestCase):
    def test_training_green_times_and_release_intervals(self):
        cycles = [{"start": 100, "end": 139, "items": [
            {"stage": "1", "start": 100, "end": 119, "duration": 20},
            {"stage": "2", "start": 120, "end": 139, "duration": 20},
        ]}]
        for names, movements in CASES:
            for name in names:
                with self.subTest(phase=name):
                    config = {"phase": {"1": name, "2": "P"}}
                    expected = {d: 20 if d in movements else 0 for d in DIRECTIONS}
                    self.assertEqual(_direction_green_times(cycles, config), expected)
                    self.assertEqual(calc_direction_time_from_cycles(cycles, "x", {"x": config}), expected)
                    for direction in DIRECTIONS:
                        runs = [{"start": 100, "end": 119}] if direction in movements else []
                        self.assertEqual(_movement_green_runs(cycles, config, direction), runs)

    def test_runtime_stage_evidence_activates_expected_movements(self):
        for names, movements in CASES:
            for name in names:
                with self.subTest(phase=name):
                    result = allocate_from_runtime_data(
                        "x", {}, {1000: [{"CrossId": "x", "curStageNo": "1"}]},
                        experience_table={"x": {}},
                        cross_info={"x": {"phase": {"1": name}, "LaneNo": {
                            d: {"1": "1B", "2": "1A"} for d in ["U", "D", "L", "R"]
                        }}},
                    )
                    self.assertEqual(set(result["active_directions"]), movements)

    def test_phase_aliases_preserve_final_bounded_phase_allocation(self):
        demand = {"U": 45, "D": 30, "L": 50, "R": 20,
                  "UTL": 25, "DTL": 35, "LTL": 40, "RTL": 30}
        for names, movements in CASES:
            if not movements:
                continue
            for name in names:
                with self.subTest(phase=name):
                    config = {"phase": [name], "min_pass_time": [15], "max_pass_time": [100]}
                    actual, _ = allocate_phase_times(demand, config)
                    # 单相位最低周期为 60，方向需求不会被相位别名改变。
                    self.assertEqual(actual, [60])


if __name__ == "__main__":
    unittest.main()
