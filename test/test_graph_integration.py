"""Production graph composition and deterministic control compatibility."""

import copy
import json
import os
import unittest
from unittest.mock import Mock, patch

import Lambdas

from agent.experts import RadarExpert, VideoExpert
from agent.graph import ControlGraph
from app.config import RuntimeSettings
from app.core.control.policies import BaselineController
from infra.data import TrafficDataHub
from phase_check import phase_check
from test.fixtures.v2_baseline_controller import (
    FIXED_TIME, FIXTURE, compact_round, full_replay,
)
from test import test_datahub_integration as datahub_tests
from test.test_decision_pipeline import _Lambdas
from test.test_expert_integration import composed_application, ingest_observations


class GraphIntegrationTest(unittest.TestCase):
    def make_pipeline(self, selector):
        pipeline, hub = datahub_tests.DataHubIntegrationTest()._make_pipeline(selector)
        graph = ControlGraph(
            hub, primary_expert=VideoExpert(hub), fallback_expert=RadarExpert(hub),
            control_policy=pipeline.control_policy,
        )
        pipeline.decision_graph = graph
        return pipeline, hub, graph

    def test_composition_shares_hub_policy_and_experts_without_any_llm_objects(self):
        with patch("runtime.application.OpenAICompatibleLLMClient") as client, patch(
            "runtime.application.QwenSignalTimingAgent",
        ) as qwen, patch("runtime.application.QwenToolRouterAgent") as router, patch(
            "runtime.application.ControlProcessAgent",
        ) as controller, composed_application(llm_required=True) as app:
            self.assertIsInstance(app.decision_graph, ControlGraph)
            self.assertIs(app.decision_pipeline.decision_graph, app.decision_graph)
            self.assertIsNone(app.llm_client)
            self.assertFalse(app.llm_required)
            harness = app.http_server.agent_harness
            self.assertIsNone(harness.qwen_agent)
            self.assertIsNone(harness.qwen_tool_router_agent)
            self.assertIsNone(harness.control_process_agent)
            self.assertIsNone(harness.autonomous_agent)
            self.assertIsNotNone(harness.signal_timing_tool)
            self.assertIsNotNone(harness.symbolic_agent)
            response = harness.handle("symbolic", {
                "action": "results.latest", "arguments": {"limit": 1},
            })
            self.assertEqual(response["status"], "success")
            self.assertEqual(response["result"]["status"], "ok")
            for factory in (client, qwen, router, controller):
                factory.assert_not_called()

    def test_disabled_llm_skips_startup_health_check_and_still_runs_control(self):
        with composed_application() as app, patch.object(
            app, "_check_llm_ready", side_effect=AssertionError("LLM is disabled"),
        ) as health, patch.object(app.http_server, "start"), patch.object(
            app.tcp_server, "start_broadcast_thread",
        ), patch.object(app, "_run_decision_loop"):
            app.start()
            self.assertIsNotNone(app._decision_thread)
            health.assert_not_called()
            with patch.object(
                app.decision_pipeline, "dqn_select",
                return_value=([25] + [0] * 8 + [1], {}, [], {}),
            ) as selector, patch.object(
                app.decision_pipeline, "coordinate", side_effect=lambda action, *_args: action,
            ), patch.object(app.decision_pipeline, "phase_check", side_effect=lambda action: (action, {})):
                result = app.decision_pipeline.run_once()
            self.assertEqual(len(result), len(Lambdas.intersection_list))
            self.assertEqual(selector.call_count, len(Lambdas.intersection_list))
            health.assert_not_called()

    def test_enabled_llm_preserves_existing_client_and_agent_composition(self):
        with composed_application(llm_enabled=True, llm_required=True) as app:
            self.assertIsNotNone(app.llm_client)
            self.assertTrue(app.llm_required)
            harness = app.http_server.agent_harness
            self.assertIs(harness.qwen_agent.llm_client, app.llm_client)
            self.assertIs(harness.qwen_tool_router_agent.llm_client, app.llm_client)
            self.assertIs(harness.control_process_agent.llm_client, app.llm_client)

    def test_graph_captures_before_selection_and_preserves_dynamic_callback_and_identity(self):
        raw = ([25] + [0] * 8 + [1], {"start": 3}, [1] * 8, {"exp": 1})
        pipeline, hub, _graph = self.make_pipeline(Mock(side_effect=AssertionError("replaced")))
        captured = []

        def selector(request):
            captured.append(copy.deepcopy(hub.latest("100")))
            request.traffic_vector[0] = 999
            request.previous_coordinate["100"]["phase"][0] = 999
            return raw

        pipeline.dqn_select = Mock(side_effect=selector)
        pipeline.coordinate = Mock(side_effect=lambda action, *_args: action)
        pipeline.last_coordinate_set = {"100": {"phase": [3]}}
        with patch("time.time", return_value=FIXED_TIME):
            result = pipeline.run_once()
        pipeline.dqn_select.assert_called_once()
        pipeline.coordinate.assert_called_once()
        self.assertEqual(len(pipeline.coordinate.call_args.args), 4)
        self.assertIs(result[0]["action"], raw[0])
        self.assertIs(result[0]["model"], raw[2])
        self.assertIs(pipeline.writer.experience[0][0], raw[3])
        self.assertEqual(captured[0].traffic_vector, [0] * 4)
        self.assertEqual(captured[0].previous_coordinate, {"100": {"phase": [3]}})
        self.assertEqual(hub.latest("100"), captured[0])

    def test_graph_preserves_missing_prediction_values_after_capture_failure(self):
        selector = Mock(return_value=([25] + [0] * 8 + [1], {}, [], {}))
        pipeline, hub, _graph = self.make_pipeline(selector)
        pipeline.flow_predictor.get_current_flow_prediction = lambda: None
        pipeline.queue_predictor.get_current_queue_prediction = lambda: None
        with patch("time.time", return_value=FIXED_TIME):
            result = pipeline.run_once()
        selector.assert_called_once()
        request = selector.call_args.args[0]
        self.assertIsNone(request.predicted_flow)
        self.assertIsNone(request.predicted_queue)
        self.assertEqual(result[0]["action"][0], 25)
        self.assertIsNone(hub.latest("100"))
        self.assertTrue(any("snapshot_validation_failed" in issue
                            for issue in hub.query("100").quality_issues))

    def test_graph_keeps_experience_failure_coordinate_and_does_not_repeat_selector(self):
        raw = ([30] + [0] * 9, {"start": 3}, [9] * 8, {"exp": 1})
        selector = Mock(return_value=raw)
        pipeline, _hub, _graph = self.make_pipeline(selector)
        pipeline.writer.write_experience = Mock(side_effect=OSError("disk full"))
        result, _, _, _ = pipeline._process_data()
        selector.assert_called_once()
        self.assertEqual(result["100"], _Lambdas.intersection_result_lambda)
        self.assertIs(pipeline.last_coordinate_set["100"], raw[1])
        pipeline.writer.write_experience.assert_called_once_with(raw[3], "100")

    def test_graph_preserves_selector_failure_default_result_without_retry(self):
        selector = Mock(side_effect=TimeoutError("selector is not a read-only expert"))
        pipeline, _hub, _graph = self.make_pipeline(selector)
        result, _, _, _ = pipeline._process_data()
        selector.assert_called_once()
        self.assertEqual(result["100"], _Lambdas.intersection_result_lambda)
        self.assertEqual(pipeline.last_coordinate_set, {"100": {}})
        self.assertEqual(pipeline.writer.experience, [])

    def test_graph_coordination_failure_preserves_previous_warehouse_batch(self):
        selector = Mock(return_value=([25] + [0] * 8 + [1], {}, [], {}))
        pipeline, _hub, _graph = self.make_pipeline(selector)
        error = RuntimeError("coordination failed")
        pipeline.coordinate = Mock(side_effect=error)
        pipeline.result_warehouse.replace([{"id": "previous"}])
        with self.assertRaises(RuntimeError) as raised:
            pipeline.run_once()
        self.assertIs(raised.exception, error)
        selector.assert_called_once()
        pipeline.coordinate.assert_called_once()
        self.assertEqual(pipeline.result_warehouse.snapshot(), [{"id": "previous"}])
        self.assertEqual(pipeline.writer.phase_reports, [])

    def test_graph_keeps_final_validation_after_coordination_and_reserved_slot_rules(self):
        raw = [10] * 8 + [9, 1]
        order = []

        def selector(request):
            order.append("selector")
            return raw, {}, [], {"exp": 1}

        pipeline, _hub, _graph = self.make_pipeline(selector)
        original_writer = pipeline.writer.write_experience

        def write_experience(*args):
            order.append("experience")
            return original_writer(*args)

        def coordinate(action, *_args):
            order.append("coordinate")
            action["100"][0] = 30
            return action

        def validate(action):
            order.append("validate")
            return phase_check(action)

        pipeline.writer.write_experience = write_experience
        pipeline.coordinate = coordinate
        pipeline.phase_check = validate
        with patch("phase_check.intersection_result_config", {
            "100": {"1": {"0": [15, 25], "8": [3, 6]}},
        }):
            result = pipeline.run_once()
        self.assertEqual(order, ["selector", "experience", "coordinate", "validate"])
        self.assertIs(result[0]["action"], raw)
        self.assertEqual(raw[0], 25)
        self.assertEqual(raw[8], 6)
        self.assertEqual(pipeline.writer.phase_reports[0]["100"]["modifications"], [
            "Phase 0: 30 -> 25", "Phase 8: 9 -> 6",
        ])

    def test_graph_preserves_two_round_control_diagnostics_and_tcp_golden(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        hub = TrafficDataHub(lambdas_module=Lambdas, memory_window=2)
        controller = BaselineController()
        graph = ControlGraph(
            hub, primary_expert=VideoExpert(hub), fallback_expert=RadarExpert(hub),
            control_policy=controller,
        )
        round_times = set()
        graph_calls = []

        def selector(request):
            if request.current_time not in round_times:
                ingest_observations(hub, request.current_time)
                round_times.add(request.current_time)
            snapshot = hub.capture(request)
            self.assertIsNotNone(snapshot)
            decision = graph.execute_legacy(request, snapshot=snapshot)
            graph_calls.append((request.cross_id, decision.used_fallback))
            return decision.selection

        actual = full_replay(selector, controller.coordinate_legacy)
        self.assertEqual(actual, full_replay())
        self.assertEqual(len(graph_calls), 372)
        self.assertTrue(any(not fallback for _cross_id, fallback in graph_calls))
        self.assertTrue(any(fallback for _cross_id, fallback in graph_calls))
        for index, result in enumerate(actual):
            with self.subTest(round=index):
                self.assertEqual(compact_round(result), golden["rounds"][index])
                self.assertEqual(len(result["tcp_frames"]), 186)
                self.assertTrue(all(frame.endswith(b"\n") for frame in result["tcp_frames"]))
        for intersection_id in Lambdas.intersection_list:
            self.assertEqual(len(hub.history(intersection_id)), 2)


class GraphLLMSettingsTest(unittest.TestCase):
    def load_settings(self, environment):
        with patch.dict(os.environ, environment, clear=True), patch("app.config._load_dotenv"):
            return RuntimeSettings.from_environment().validate()

    def test_default_llm_flag_preserves_previous_enabled_behavior(self):
        self.assertTrue(self.load_settings({}).llm_enabled)

    def test_plain_and_prefixed_flags_are_supported_with_aitc_priority(self):
        self.assertFalse(self.load_settings({"LLM_ENABLED": "false"}).llm_enabled)
        self.assertFalse(self.load_settings({"AITC_LLM_ENABLED": "off"}).llm_enabled)
        self.assertTrue(self.load_settings({
            "AITC_LLM_ENABLED": "yes", "LLM_ENABLED": "false",
        }).llm_enabled)
        self.assertFalse(self.load_settings({
            "AITC_LLM_ENABLED": "0", "LLM_ENABLED": "true",
        }).llm_enabled)

    def test_invalid_flags_fail_before_assembly(self):
        for value in ("invalid", "2", "none"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "boolean"):
                self.load_settings({"LLM_ENABLED": value})
        for value in ("false", None, 0, 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "boolean"):
                RuntimeSettings(llm_enabled=value).validate()

    def test_disabled_llm_does_not_require_unused_client_configuration(self):
        settings = RuntimeSettings(
            llm_enabled=False, llm_required=True, llm_base_url="", llm_model="",
            llm_timeout_seconds=0, llm_max_tokens=0,
        ).validate()
        self.assertFalse(settings.llm_enabled)
        with self.assertRaisesRegex(ValueError, "llm_base_url"):
            RuntimeSettings(llm_enabled=True, llm_base_url="").validate()


if __name__ == "__main__":
    unittest.main()
