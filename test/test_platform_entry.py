"""公共平台入口和本地策略登记的行为回归。"""
import inspect
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import lib.DQN_Select as selectors
from lib import intersection_strategy as strategy
from lib.road_groups import TONGZHOU_19, TONGZHOU_49, road_group
from lib.control_functions.global_processors.flow_control import process_flow_intersection
from lib.control_functions.global_processors.finalization import finalize_plan_values
from runtime.result_formatter import _plan_id_for


def config(phases):
    return {"phase": phases, "min_pass_time": [5]*len(phases),
            "max_pass_time": [100]*len(phases)}


class PlatformEntryTests(unittest.TestCase):
    def test_all_49_aliases_preserve_call_signature_and_orchestration(self):
        # 保留外部旧调用名；只模拟经验选择和观测特征，不依赖测试机的经验表。
        args = [object() for _ in range(11)]
        expected_names = ["traffic_vector", "queue_vector", "traffic_vector_duration2", "current_time",
                          "flow_map_single_intersection", "queue_map_single_intersection",
                          "stage_map_single_intersection", "extend_map_single_intersection",
                          "coordinate_map_set", "cur_flow_pre_map", "cur_queue_pre_map"]
        for road in TONGZHOU_49:
            with self.subTest(road=road), patch.object(selectors, "get_model_map", return_value="model") as model, \
                    patch.object(selectors, "get_exp", return_value="experience") as experience, \
                    patch.object(selectors, "select_pilot_schedule", return_value=[31, 42]+[0]*8) as pilot:
                old_name = getattr(selectors, "DQN_select_"+road)
                self.assertEqual(list(inspect.signature(old_name).parameters), expected_names)
                result = old_name(*args)
                self.assertEqual(result, ([31, 42]+[0]*8, {"Start1": 1, "start2": 0}, "model", "experience"))
                model.assert_called_once_with(args[0], args[5], args[6])
                experience.assert_called_once_with(args[0], args[2])
                pilot.assert_called_once_with(road, [0]*10, args[4], args[7])

    def test_registered_19_roads_preserve_their_fallbacks_through_shared_entry(self):
        flow_only = {"1700086", "1700275", "1700276"}
        timetable = {"1700448", "1700449", "1700450", "1700542", "1700545"}
        args = {name: {} for name in inspect.signature(selectors.DQN_select).parameters}
        flow, extend = args["flow_map_single_intersection"], args["extend_map_single_intersection"]
        args.update(current_time=1)
        del args["cross_id"]
        for road in TONGZHOU_19 - {"1700458"}:
            with (
                self.subTest(road=road),
                patch.object(selectors, "get_model_map", return_value="model"),
                patch.object(selectors, "get_exp", return_value="experience"),
                patch.object(selectors, "chuli_shuju", return_value=[34] * 10) as staged,
                patch.object(selectors, "chuli_shuju3", return_value=[42] * 10) as flow_lookup,
                patch.object(selectors, "select_pilot_schedule", side_effect=lambda _, fallback, f, e: fallback) as pilot,
            ):
                result = selectors.DQN_select(**args, cross_id=road)
                expected = [0] * 10 if road in timetable else [42 if road in flow_only else 34] * 10
                self.assertEqual(result, (expected, {"Start1": 1, "start2": 0}, "model", "experience"))
                pilot.assert_called_once_with(road, expected, flow, extend)
                if road in flow_only:
                    flow_lookup.assert_called_once_with(road, flow)
                else:
                    flow_lookup.assert_not_called()
                if road not in (flow_only | timetable):
                    staged.assert_called_once_with(road, flow, extend)
                else:
                    staged.assert_not_called()

    def test_new_road_outside_49_uses_shared_entry_without_offline_lookup(self):
        road = "999999"
        arguments = {name: {} for name in inspect.signature(selectors.DQN_select).parameters}
        arguments.update(cross_id=road, current_time=1)
        with patch.object(strategy, "PLATFORM_PHASE_ROAD_IDS", {road}), \
                patch.dict(selectors.Cross_Video, {road: {"Cross_type": "Video"}}), \
                patch.object(selectors, "get_model_map", return_value={}), \
                patch.object(selectors, "get_exp", return_value={}), \
                patch.object(selectors, "select_pilot_schedule", return_value=[30]*2+[0]*8) as pilot, \
                patch.object(selectors, "Get_time_map", side_effect=AssertionError("不得走旧时段入口")), \
                patch.object(selectors, "chuli_shuju", side_effect=AssertionError("不得读取离线经验")):
            self.assertIsNone(road_group(road))
            result = selectors.DQN_select(**arguments)
            self.assertEqual(result[0][:2], [30,30])
            self.assertEqual(pilot.call_args.args[0], road)

    def test_new_default_program_and_forced_program_survive_finalization(self):
        road = "999999"
        states = {"3": config(["LR", "UD"]), "2": config(["UD", "LR"])}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"overrides.json"
            path.write_text('{"999999": 3}')
            with patch.object(strategy, "PLATFORM_PHASE_ROAD_IDS", {road}), \
                    patch.object(strategy, "_PLAN_OVERRIDES_PATH", path), \
                    patch.object(strategy, "_PLAN_OVERRIDES_CACHE", {"signature": None, "data": {}}):
                for forced, expected in [("3", [80,40]), ("2", [40,80])]:
                    plan, report = process_flow_intersection(
                        road, [40,30,80,70]+[0]*6, states, 17,
                        lambda rid, state: forced, lambda rid: {})
                    self.assertTrue(report["success"], report)
                    self.assertIsNone(report["road_group"])
                    self.assertEqual(plan[:2], expected)
                    plans = {road: plan}
                    with patch("lib.control_functions.global_processors.finalization.apply_floating_value",
                               return_value=(plans, {})):
                        plans, _ = finalize_plan_values(plans, road_info={road: states})
                    self.assertEqual(_plan_id_for(road, plans[road][9]), int(forced))
                self.assertEqual(_plan_id_for(road, 0), 3)
                plan, report = process_flow_intersection(
                    road, [0]*10, states, 17, lambda rid, state: "9", lambda rid: {})
                self.assertTrue(report["success"], report)
                self.assertEqual(plan[9], 3)
                self.assertEqual(plan[:2], [30,30])

    def test_explicit_pilot_and_learning_scopes_remain_authoritative(self):
        from lib.data_ANS import flow_allocator_shadow as shadow, experience_runtime as runtime
        env = {"AITC_FLOW_ALLOCATOR_PILOT_ROADS": "190",
               "AITC_EXPERIENCE_POOL_ROADS": "190", "AITC_EXPERIENCE_TABLE_UPDATE_ROADS": "191"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(shadow._target_road_ids(), {"190"})
            self.assertEqual(runtime._configured_update_roads(), {"191"})
            self.assertEqual(runtime._configured_collection_roads(), ["190", "191"])


if __name__ == "__main__":
    unittest.main()
