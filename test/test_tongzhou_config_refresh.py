"""19组旧方向算法的相位和车道配置更新，无需重启并保持单次计算快照一致。"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lib import movement_experience_timing as timing


def config(phase, lane_type="1B"):
    return {"phase":{"1":phase},
            "LaneNo":{direction:{"0":lane_type} for direction in ("U","D","L","R")}}


class TongzhouConfigRefreshTests(unittest.TestCase):
    def test_atomic_update_changes_phase_and_lane_use_for_19_only(self):
        for road in ["1700125","1700448"]:
            with self.subTest(road=road), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/"cross.json"
                path.write_text(json.dumps({road:config("LR","1A")}))
                with patch.object(timing,"info",path), \
                        patch.object(timing,"lines3",{road:config("LR","1A")}):
                    self.assertEqual(timing.movement_lane_sets(road,"U"),(set(),{0}))
                    replacement = Path(directory)/"update.json"
                    replacement.write_text(json.dumps({road:config("UD","1B")}))
                    replacement.replace(path)
                    self.assertEqual(timing.movement_lane_sets(road,"U"),({0},set()))
                    self.assertEqual(timing._cross_config_for_road(road)["phase"],{"1":"UD"})
        with patch.object(timing,"lines3",{"1300069":config("LR")}), \
                patch.object(timing,"load_json_cached",side_effect=AssertionError("历史其他路口不迁移")):
            self.assertEqual(timing._cross_config_for_road("1300069")["phase"],{"1":"LR"})

    def test_control_uses_one_current_snapshot_for_phase_and_lane_lookup(self):
        road = "1700125"
        table = {d:{"10":[100]+[0]*9} for d in ("U","D","L","R","UTL","DTL","LTL","RTL")}
        flow = {1000:{"pass":{d:[1]+[0]*9 for d in ("U","D","L","R")}}}
        extend = {1000:[{"time":1000,"curStageNo":"1"}]}
        original = copy.deepcopy((flow,extend))
        outputs = []
        for phase in ["LR","UD"]:
            with patch.object(timing,"load_json_cached",return_value={road:config(phase)}) as reader, \
                    patch.object(timing,"jiangyan_biao_get",return_value=table), patch("builtins.print"):
                outputs.append(timing.chuli_shuju(road,flow,extend))
                reader.assert_called_once()
        self.assertEqual(outputs[0][:4],[0,0,10,10])
        self.assertEqual(outputs[1][:4],[10,10,0,0])
        self.assertEqual((flow,extend),original)


if __name__ == "__main__":
    unittest.main()
