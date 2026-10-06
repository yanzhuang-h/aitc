"""Opt-in cognition shares the real graph and preserves the production control ABI."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

import Lambdas

from agent.cognitive import CognitiveController
from agent.control_tools import ControlAgentTools
from agent.graph import ControlGraph
from app.config import ControlAgentSettings, RuntimeSettings
from app.core.control.policies import BaselineController
from app.infrastructure.llm import ModelGateway, ModelResponse, MockProvider
from infra.data import TrafficDataHub
from infra.data.traffic_schemas import TrafficSnapshot
from lib.control_functions.types import IntersectionControlRequest
from runtime.application import create_application
from test.fixtures.v2_baseline_controller import FIXTURE, compact_round, full_replay, isolated_runtime
from test.test_control_graph import DIRECT_ROUTE, ROAD, radar_state, selection, video_state
from test.test_expert_integration import ingest_observations


def action(tool, **arguments):
    return ModelResponse(content=json.dumps({"tool": tool, "arguments": arguments}))


class _ReviewerProvider(MockProvider):
    """Return constrained actions from the supplied host phase, never invent observations."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def invoke(self, request):
        self.calls += 1
        context = json.loads(request.messages[-1].content)
        if context["phase"] == "planner":
            return action("run_control_policy")
        return action("review_signal_plan", decision="WARN", reason="Missing video evidence; keep the baseline candidate.")


@contextmanager
def cognitive_application(provider="mock", *, llm_enabled=True, control_enabled=True):
    with tempfile.TemporaryDirectory(prefix="aitc-phase7-") as directory:
        root = Path(directory)
        settings = RuntimeSettings(
            model_provider=provider, llm_enabled=llm_enabled,
            runtime_data_dir=root / "history", runtime_output_dir=root / "output",
            prediction_data_dir=root / "prediction", enable_config_sync=False,
            enable_prediction_scheduler=False, enable_experience_pool_scheduler=False,
            control_agent=ControlAgentSettings(enabled=control_enabled, timeout_seconds=0.1),
        )
        app = create_application(settings=settings)
        try:
            yield app
        finally:
            app.stop()


class CognitiveGraphIntegrationTest(unittest.TestCase):
    def make_graph(self, responses, *, primary=None, candidate=None):
        hub = TrafficDataHub(lambdas_module=Lambdas)
        video = Mock()
        video.extract.return_value = primary if primary is not None else video_state(flow=False)
        radar = Mock()
        radar.extract.side_effect = lambda road: radar_state(road)
        gateway = ModelGateway(MockProvider(responses))
        tools = ControlAgentTools(hub, video, radar)
        cognitive = CognitiveController(gateway, tools, ControlAgentSettings(enabled=True))
        selector = Mock(return_value=candidate if candidate is not None else selection())
        graph = ControlGraph(
            hub, primary_expert=video, fallback_expert=radar,
            control_policy=BaselineController(selector=selector, coordinator=Mock()),
            cognitive_controller=cognitive,
        )
        return graph, gateway, selector, video, radar

    def test_application_shares_gateway_datahub_and_experts_with_cognition(self):
        with cognitive_application() as app:
            self.assertIs(app.cognitive_agent.gateway, app.model_gateway)
            self.assertIs(app.cognitive_agent.tools, app.control_agent_tools)
            self.assertIs(app.control_agent_tools.datahub, app.datahub)
            self.assertIs(app.control_agent_tools.video_expert, app.experts["video"])
            self.assertIs(app.control_agent_tools.radar_expert, app.experts["radar"])
            self.assertIs(app.decision_graph.cognitive_controller, app.cognitive_agent)

    def test_disabled_llm_or_control_switch_omits_cognition(self):
        cases = ((False, True, "qwen"), (True, False, "mock"), (True, True, "disabled"))
        for llm, control, provider in cases:
            with self.subTest(provider=provider, llm=llm, control=control), cognitive_application(
                provider, llm_enabled=llm, control_enabled=control,
            ) as app:
                self.assertIsNone(app.cognitive_agent)
                self.assertIsNone(app.decision_graph.cognitive_controller)
                self.assertIsNotNone(app.control_agent_tools)

    def test_complete_video_fast_path_makes_no_model_calls(self):
        graph, gateway, selector, _video, radar = self.make_graph([], primary=video_state())
        with patch.object(gateway, "invoke_sync", wraps=gateway.invoke_sync) as invoke:
            decision = graph.execute_legacy(IntersectionControlRequest(cross_id=ROAD, current_time=1))
        invoke.assert_not_called()
        radar.extract.assert_not_called()
        selector.assert_called_once()
        self.assertEqual(decision.route, DIRECT_ROUTE)
        self.assertIsNone(decision.cognition)

    def test_planner_radar_request_is_reused_and_selector_runs_once(self):
        graph, _gateway, selector, _video, radar = self.make_graph([
            action("query_radar_state"), action("run_control_policy"),
            action("review_signal_plan", decision="WARN", reason="Video flow missing."),
        ])
        request = IntersectionControlRequest(cross_id=ROAD, current_time=1, traffic_vector=[3, 4])
        before = copy.deepcopy(request)
        snapshot = TrafficSnapshot(cross_id=ROAD, current_time=1)
        decision = graph.execute_legacy(request, snapshot=snapshot)
        self.assertEqual(request, before)
        radar.extract.assert_called_once_with(ROAD)
        selector.assert_called_once_with(request)
        self.assertIs(decision.selection, selector.return_value)
        self.assertEqual(decision.cognition.model_calls, 3)
        self.assertEqual(decision.cognition.review.decision, "WARN")
        self.assertEqual(decision.route, (
            "load_context", "primary_expert", "planner", "fallback_expert",
            "control_policy", "validate", "review",
        ))

    def test_review_decisions_keep_original_selection_and_request(self):
        for decision, extra in (
            ("ACCEPT", {}), ("WARN", {}), ("FALLBACK", {}),
            ("REQUEST_MORE_DATA", {"source": "radar"}),
            ("SUGGEST_ADJUSTMENT", {"suggestion": "Investigate the queue imbalance."}),
        ):
            with self.subTest(decision=decision):
                graph, _gateway, selector, _video, _radar = self.make_graph([
                    action("run_control_policy"),
                    action("review_signal_plan", decision=decision, reason="Observed state reviewed.", **extra),
                ])
                raw_before = copy.deepcopy(selector.return_value)
                result = graph.execute_legacy(IntersectionControlRequest(cross_id=ROAD, current_time=1))
                self.assertEqual(result.selection, raw_before)
                self.assertIs(result.selection, selector.return_value)
                self.assertEqual(result.cognition.review.decision, decision)
                selector.assert_called_once()

    def test_primary_failure_still_uses_planner_radar_and_baseline(self):
        graph, _gateway, selector, video, _radar = self.make_graph([
            action("run_control_policy"),
            action("review_signal_plan", decision="WARN", reason="Video unavailable."),
        ])
        video.extract.side_effect = TimeoutError("read failed")
        result = graph.execute_legacy(IntersectionControlRequest(cross_id=ROAD, current_time=1))
        self.assertEqual(video.extract.call_count, 2)
        self.assertTrue(result.quality_issues)
        self.assertTrue(result.used_fallback)
        self.assertIsNotNone(result.cognition.review)
        selector.assert_called_once()

    def test_invalid_candidate_is_not_sent_to_model_as_a_valid_plan(self):
        raw = ([-1] + [0] * 9, {}, [], {})
        graph, _gateway, selector, _video, _radar = self.make_graph([action("run_control_policy")], candidate=raw)
        result = graph.execute_legacy(IntersectionControlRequest(cross_id=ROAD, current_time=1))
        self.assertIs(result.selection, raw)
        self.assertIsNone(result.candidate)
        self.assertNotIn("review", result.route)
        self.assertIsNone(result.cognition.review)
        selector.assert_called_once()

    def test_opaque_snapshot_summary_failure_keeps_baseline_execution(self):
        graph, gateway, selector, _video, _radar = self.make_graph([])
        snapshot = TrafficSnapshot(cross_id=ROAD, current_time=1, flow_map={1: {"opaque": object()}})
        with patch.object(gateway, "invoke_sync", wraps=gateway.invoke_sync) as invoke:
            result = graph.execute_legacy(
                IntersectionControlRequest(cross_id=ROAD, current_time=1), snapshot=snapshot,
            )
        self.assertIs(result.selection, selector.return_value)
        selector.assert_called_once()
        invoke.assert_not_called()
        self.assertEqual(result.cognition.reason, "context_error")
        self.assertTrue(result.cognition.errors)

    def test_shared_graph_does_not_share_sessions_or_candidates_between_threads(self):
        graph, gateway, selector, video, _radar = self.make_graph([])
        gateway.provider = _ReviewerProvider()
        roads = ["1300068", "1300069", "1300070", "1300271"] * 3
        video.extract.side_effect = lambda road: video_state(road, flow=False)
        selector.side_effect = lambda request: selection(request.cross_id)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(
                lambda road: graph.execute_legacy(IntersectionControlRequest(cross_id=road, current_time=1)),
                roads,
            ))
        self.assertEqual(len({id(result.cognition) for result in results}), len(roads))
        for road, result in zip(roads, results):
            self.assertEqual(result.candidate.intersection_id, road)
            self.assertEqual(result.selection[1]["road"], road)
            self.assertEqual(result.cognition.model_calls, 2)
            self.assertTrue(all(item.intersection_id == road for item in result.cognition.observations))
        self.assertEqual(selector.call_count, len(roads))

    def test_model_timeout_and_unavailability_preserve_actual_186_road_output(self):
        with isolated_runtime(), cognitive_application("disabled") as app:
            app.decision_pipeline.worker_count = 1
            expected = app.decision_pipeline.run_once()
        for failure in (TimeoutError("model socket expired"), URLError("no model server")):
            with self.subTest(failure=failure), isolated_runtime(), cognitive_application("qwen") as app:
                app.decision_pipeline.worker_count = 1
                with patch.object(app.model_gateway.provider.client, "chat", side_effect=failure) as chat:
                    actual = app.decision_pipeline.run_once()
                self.assertEqual(actual, expected)
                self.assertEqual(len(actual), 186)
                self.assertEqual(chat.call_count, 1)

    def test_enabled_cognition_preserves_two_round_control_and_tcp_golden(self):
        hub = TrafficDataHub(lambdas_module=Lambdas, memory_window=2)
        from agent.experts import RadarExpert, VideoExpert

        video, radar = VideoExpert(hub), RadarExpert(hub)
        controller = BaselineController()
        provider = _ReviewerProvider()
        cognitive = CognitiveController(
            ModelGateway(provider), ControlAgentTools(hub, video, radar),
            ControlAgentSettings(enabled=True),
        )
        graph = ControlGraph(
            hub, primary_expert=video, fallback_expert=radar,
            control_policy=controller, cognitive_controller=cognitive,
        )
        round_times = set()
        decisions = []

        def selector(request):
            if request.current_time not in round_times:
                ingest_observations(hub, request.current_time)
                round_times.add(request.current_time)
            result = graph.execute_legacy(request, snapshot=hub.capture(request))
            decisions.append(result)
            return result.selection

        actual = full_replay(selector, controller.coordinate_legacy)
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for index, result in enumerate(actual):
            self.assertEqual(compact_round(result), golden["rounds"][index])
        self.assertEqual(len(decisions), 372)
        self.assertTrue(any(item.cognition is None for item in decisions))
        reviewed = [item for item in decisions if item.cognition is not None]
        self.assertTrue(reviewed)
        self.assertTrue(all(item.cognition.review.decision == "WARN" for item in reviewed))
        self.assertEqual(provider.calls, 2 * len(reviewed))
