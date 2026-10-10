"""在全局协调与 TCP 格式化之间验证真实安全门，守住冻结的 186 路口输出。"""

import copy
import json
import unittest
from unittest.mock import Mock, patch

from app.core.control.policies import BaselineController
from app.core.control.safety_engine import ControlSafetyEngine
from phase_check import get_intersection_result_config, phase_check
from test.fixtures.v2_baseline_controller import FIXTURE, compact_round, full_replay, isolated_runtime, sensor_request
import test.test_decision_pipeline as pipeline_tests
from test.test_model_gateway_integration import model_application
from test.unit.test_safety_engine import CONFIG, PLAN, ROAD, engine


class SafetyGateIntegrationTest(unittest.TestCase):
    def pipeline(self, *, selector=None, coordinator=None, gate=None):
        return pipeline_tests.PeriodicDecisionPipelineTest()._make_pipeline(
            selector=selector or (lambda request: (list(PLAN), {}, [], {})),
            coordinator=coordinator or (lambda action, *_args: action),
            safety_engine=gate or engine(),
        )

    def test_production_composition_always_installs_gate_even_without_llm(self):
        with model_application("disabled") as app:
            self.assertIsInstance(app.decision_pipeline.safety_engine, ControlSafetyEngine)
            self.assertIs(app.decision_pipeline.safety_engine.config_supplier, get_intersection_result_config)
            self.assertIs(app.decision_pipeline.safety_engine.fallback_loader.__self__, app.decision_pipeline.control_policy)

    def test_two_real_rounds_preserve_plans_payloads_tcp_and_old_report_fields(self):
        gate = ControlSafetyEngine(config_supplier=get_intersection_result_config, phase_check=phase_check,
                                  logger=Mock())
        all_reports = []

        def finalize(plans):
            final, reports = gate.finalize(plans)
            all_reports.append(copy.deepcopy(reports))
            # 新增安全证据在独立断言中核对，原报告字段仍与冻结 fixture 比较。
            legacy_reports = {road: {key: report[key] for key in ("check_status", "msg", "modifications")}
                              for road, report in reports.items()}
            return final, legacy_reports

        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with patch("test.fixtures.v2_baseline_controller.phase_checker.phase_check", finalize):
            actual = full_replay()
        for n, result in enumerate(actual):
            self.assertEqual(compact_round(result), golden["rounds"][n])
            reports = all_reports[n]
            self.assertEqual(sum(report["safety_status"] == "partial" for report in reports.values()), 48)
            self.assertEqual(sum(report["safety_status"] == "valid" for report in reports.values()), 134)
            self.assertEqual(sum(report["safety_status"] == "no_action" for report in reports.values()), 4)
            self.assertTrue(all(report["fallback_source"] is None for report in reports.values()))
            self.assertIsNone(reports["2719089"]["safe"])
            self.assertIn("intersection_config", reports["2719089"]["missing_rules"])

    def test_global_coordination_corruption_restores_captured_baseline_candidate(self):
        def coordinate(action, *_args):
            action[ROAD][0], action[ROAD][1], action[ROAD][2] = 20, 0, 30
            return action

        pipeline = self.pipeline(coordinator=coordinate)
        result = pipeline.run_once()
        self.assertEqual(result[0]["action"], PLAN)
        report = pipeline.writer.phase_reports[0][ROAD]
        self.assertEqual(report["fallback_source"], "baseline_candidate")
        self.assertIn("phase_2_after_zero_terminator", report["fallback_reason"])
        self.assertEqual(pipeline.result_warehouse.snapshot(), result)
        self.assertEqual(len(pipeline.writer.experience), 1)

    def test_missing_coordinator_road_is_checked_and_falls_back(self):
        pipeline = self.pipeline(coordinator=lambda *_args: {})
        result = pipeline.run_once()
        self.assertEqual(result[0]["action"], PLAN)
        self.assertEqual(pipeline.writer.phase_reports[0][ROAD]["fallback_source"], "baseline_candidate")

    def test_invalid_candidate_and_invalid_final_do_not_reach_formatter(self):
        pipeline = self.pipeline(selector=lambda _request: ([1, 0, 30] + [0] * 6 + [1], {}, [], {}))
        result = pipeline.run_once()
        self.assertEqual(result[0]["action"], [0] * 10)
        report = pipeline.writer.phase_reports[0][ROAD]
        self.assertEqual(report["fallback_source"], "no_action")
        self.assertIsNone(report["safe"])

    def test_unexpected_safety_error_does_not_publish_a_new_batch(self):
        gate = Mock()
        gate.finalize.side_effect = RuntimeError("validator programming error")
        pipeline = self.pipeline(gate=gate)
        pipeline.result_warehouse.replace([{"id": "previous"}])
        with self.assertRaisesRegex(RuntimeError, "validator programming error"):
            pipeline.run_once()
        self.assertEqual(pipeline.result_warehouse.snapshot(), [{"id": "previous"}])
        self.assertEqual(pipeline.writer.phase_reports, [])

    def test_real_timetable_fallback_uses_existing_baseline_schedule(self):
        controller = BaselineController()
        with isolated_runtime():
            request = sensor_request("1300068")
            schedule = controller.fallback_legacy(request.cross_id, request.current_time)
            self.assertIsInstance(schedule, list)
            gate = ControlSafetyEngine(config_supplier=get_intersection_result_config, phase_check=phase_check,
                                       fallback_loader=controller.fallback_legacy, logger=Mock())
            final, reports = gate.finalize({request.cross_id: None})
            self.assertEqual(reports[request.cross_id]["fallback_source"], "timetable")
            self.assertTrue(reports[request.cross_id]["safe"])
            self.assertEqual(gate.check(request.cross_id, final[request.cross_id]).status, "valid")

    def test_post_coordinate_bounds_are_clamped_before_publication(self):
        def coordinate(action, *_args):
            action[ROAD][0] = 999
            return action

        pipeline = self.pipeline(coordinator=coordinate)
        result = pipeline.run_once()
        self.assertEqual(result[0]["action"][0], 40)
        report = pipeline.writer.phase_reports[0][ROAD]
        self.assertTrue(report["safe"])
        self.assertIsNone(report["fallback_source"])
        self.assertTrue(report["modifications"])


if __name__ == "__main__":
    unittest.main()
