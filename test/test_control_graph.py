"""真实 LangGraph 路由、只读重试及旧控制边界的回归测试。"""

import random
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from agent.graph import ControlGraph
from agent.experts._state import ExpertContractError
from app.core.control.adapters import signal_plan_to_legacy
from app.core.control.policies import BaselineController
from infra.data.traffic_schemas import ExpertTrafficState, TrafficSnapshot
from lib.control_functions.types import IntersectionControlRequest


ROAD = "1300068"
DIRECT_ROUTE = ("load_context", "primary_expert", "control_policy", "validate")
FALLBACK_ROUTE = (
    "load_context", "primary_expert", "fallback_expert", "control_policy", "validate",
)


def video_state(road=ROAD, *, confidence=1, flow=True, queue=True, missing=None):
    return ExpertTrafficState(
        source="video",
        observation=TrafficSnapshot(
            cross_id=road, current_time=1,
            flow_map={1: {"count": 3}} if flow else {},
            queue_map={1: {"queue": 2}} if queue else {},
        ),
        confidence=confidence,
        missing_fields=[] if missing is None else missing,
    )


def radar_state(road=ROAD, *, confidence=1):
    return ExpertTrafficState(
        source="radar",
        observation=TrafficSnapshot(
            cross_id=road, current_time=1, radar_map={1: {"observed": road}},
        ),
        confidence=confidence,
    )


def selection(road=ROAD):
    return ([15.5, 20, 0, 99, 0, 0, 0, 0, 7, 2],
            {"road": road}, [road], {"experience": road})


class ControlGraphTest(unittest.TestCase):
    def setUp(self):
        self.request = IntersectionControlRequest(cross_id=ROAD, current_time=1)
        self.primary = Mock()
        self.primary.extract.return_value = video_state()
        self.fallback = Mock()
        self.fallback.extract.return_value = radar_state()
        self.raw_selection = selection()
        self.selector = Mock(return_value=self.raw_selection)
        self.policy = BaselineController(selector=self.selector, coordinator=Mock())
        self.hub = Mock()
        self.graph = ControlGraph(
            self.hub, primary_expert=self.primary, fallback_expert=self.fallback,
            control_policy=self.policy,
        )

    def test_compiles_real_langgraph_and_takes_sufficient_video_branch(self):
        self.assertIsInstance(self.graph.graph, CompiledStateGraph)
        result = self.graph.execute_legacy(self.request)
        self.assertEqual(result.route, DIRECT_ROUTE)
        self.assertFalse(result.used_fallback)
        self.assertIsNone(result.fallback)
        self.assertEqual(result.primary.observation.cross_id, ROAD)
        self.primary.extract.assert_called_once_with(ROAD)
        self.fallback.extract.assert_not_called()
        self.assertEqual(signal_plan_to_legacy(result.candidate), self.raw_selection[0])

    def test_optional_video_fields_do_not_trigger_radar_fallback(self):
        self.primary.extract.return_value = video_state(
            missing=["stage_map", "extend_map", "traffic_vector_duration2"],
        )
        result = self.graph.execute_legacy(self.request)
        self.assertEqual(result.route, DIRECT_ROUTE)
        self.fallback.extract.assert_not_called()

    def test_missing_required_observation_routes_to_radar(self):
        for flow, queue in ((False, True), (True, False), (False, False)):
            with self.subTest(flow=flow, queue=queue):
                self.primary.extract.return_value = video_state(flow=flow, queue=queue)
                self.fallback.extract.reset_mock()
                result = self.graph.execute_legacy(self.request)
                self.assertEqual(result.route, FALLBACK_ROUTE)
                self.assertTrue(result.used_fallback)
                self.assertEqual(result.fallback.source, "radar")
                self.fallback.extract.assert_called_once_with(ROAD)

    def test_low_confidence_routes_to_radar_even_with_both_maps(self):
        self.primary.extract.return_value = video_state(confidence=0.5)
        result = self.graph.execute_legacy(self.request)
        self.assertTrue(result.used_fallback)
        self.assertEqual(result.route, FALLBACK_ROUTE)

    def test_baseline_runs_with_both_experts_missing_observations(self):
        self.primary.extract.return_value = video_state(confidence=0, flow=False, queue=False)
        self.fallback.extract.return_value = radar_state(confidence=0)
        result = self.graph.execute_legacy(self.request)
        self.assertIs(result.selection, self.raw_selection)
        self.selector.assert_called_once_with(self.request)

    def test_original_request_and_all_four_result_references_are_preserved(self):
        self.request.traffic_vector = [11, 12]
        self.request.queue_vector = {"L": [13]}
        self.request.previous_coordinate = {"previous": [17]}
        self.request.predicted_flow = {"global_prediction": [19]}
        self.request.predicted_queue = {"global_prediction": [23]}
        self.request.overflow_map = {"overflow": [29]}
        result = self.graph.execute_legacy(self.request)
        self.assertIs(self.selector.call_args.args[0], self.request)
        self.assertIs(result.selection, self.raw_selection)
        for original, returned in zip(self.raw_selection, result.selection):
            self.assertIs(original, returned)
        self.assertEqual(self.request.traffic_vector, [11, 12])
        self.assertEqual(self.request.predicted_flow, {"global_prediction": [19]})
        self.assertEqual(self.request.previous_coordinate, {"previous": [17]})

    def test_dynamic_selector_overrides_policy_for_only_that_invocation(self):
        override_result = selection("override")
        override = Mock(return_value=override_result)
        result = self.graph.execute_legacy(self.request, selector=override)
        self.assertIs(result.selection, override_result)
        self.assertIs(override.call_args.args[0], self.request)
        self.selector.assert_not_called()
        self.assertIs(self.graph.select_legacy(self.request), self.raw_selection)
        self.selector.assert_called_once_with(self.request)

    def test_legacy_predictor_none_keeps_baseline_request_unchanged(self):
        self.request.predicted_flow = None
        self.request.predicted_queue = None
        result = self.graph.execute_legacy(self.request, snapshot=None)
        self.assertIs(result.selection, self.raw_selection)
        self.assertIs(self.selector.call_args.args[0], self.request)
        self.assertIsNone(self.request.predicted_flow)
        self.assertIsNone(self.request.predicted_queue)

    def test_invalid_legacy_candidate_is_reported_without_replacing_it(self):
        invalid_candidates = (
            [-1] + [0] * 9,
            [float("nan")] + [0] * 9,
            [10, 20],
            None,
        )
        for candidate in invalid_candidates:
            with self.subTest(candidate=candidate):
                raw = (candidate, {"coordinate": 1}, ["model"], {"experience": 2})
                self.selector.return_value = raw
                result = self.graph.execute_legacy(self.request)
                self.assertIs(result.selection, raw)
                self.assertIs(result.selection[0], candidate)
                self.assertIsNone(result.candidate)
                self.assertTrue(result.quality_issues)

    def test_strict_prediction_rejects_ordinary_legacy_request_before_selection(self):
        with self.assertRaises((ValidationError, TypeError)):
            self.graph.predict(self.request)
        self.selector.assert_not_called()
        self.primary.extract.assert_not_called()

    def test_strict_prediction_preserves_float_candidate_and_isolates_snapshot(self):
        snapshot = TrafficSnapshot(
            cross_id=ROAD, current_time=1, flow_map={1: {"counts": [3]}},
        )

        def select(request):
            self.assertIs(type(request), IntersectionControlRequest)
            request.flow_map[1]["counts"].append(5)
            return self.raw_selection

        self.selector.side_effect = select
        prediction = self.graph.predict(snapshot)
        self.assertEqual(prediction.intersection_id, ROAD)
        self.assertEqual(signal_plan_to_legacy(prediction), self.raw_selection[0])
        self.assertEqual(snapshot.flow_map[1]["counts"], [3])
        self.selector.assert_called_once()

    def test_strict_prediction_rejects_invalid_candidate_after_one_selection(self):
        self.selector.return_value = ([-1] + [0] * 9, {}, [], {})
        with self.assertRaises((ValidationError, ValueError)):
            self.graph.predict(TrafficSnapshot(cross_id=ROAD, current_time=1))
        self.selector.assert_called_once()

    def test_wrong_road_expert_observation_is_reported_and_does_not_replace_request(self):
        self.primary.extract.return_value = video_state(road="other-road")
        result = self.graph.execute_legacy(self.request)
        self.assertTrue(result.used_fallback)
        self.assertTrue(result.quality_issues)
        self.assertIsNone(result.primary)
        self.assertIs(self.selector.call_args.args[0], self.request)

    def test_wrong_source_primary_observation_routes_to_radar(self):
        self.primary.extract.return_value = radar_state()
        result = self.graph.execute_legacy(self.request)
        self.assertTrue(result.used_fallback)
        self.assertTrue(result.quality_issues)
        self.assertIsNone(result.primary)

    def test_malformed_expert_result_falls_back_without_retry(self):
        self.primary.extract.return_value = {"source": "video", "confidence": "bad"}
        result = self.graph.execute_legacy(self.request)
        self.assertTrue(result.used_fallback)
        self.assertTrue(result.quality_issues)
        self.primary.extract.assert_called_once_with(ROAD)
        self.selector.assert_called_once_with(self.request)

    def test_transient_primary_read_is_retried_then_uses_video_route(self):
        for error in (TimeoutError("read timeout"), ConnectionError("read disconnected")):
            with self.subTest(error=error):
                self.primary.extract.reset_mock()
                self.primary.extract.side_effect = [error, video_state()]
                result = self.graph.execute_legacy(self.request)
                self.assertEqual(self.primary.extract.call_count, 2)
                self.assertEqual(result.route, DIRECT_ROUTE)
                self.assertFalse(result.used_fallback)
        self.assertEqual(self.selector.call_count, 2)

    def test_exhausted_primary_read_routes_to_radar_and_baseline_once(self):
        self.primary.extract.side_effect = TimeoutError("read timeout")
        result = self.graph.execute_legacy(self.request)
        self.assertEqual(self.primary.extract.call_count, 2)
        self.assertEqual(result.route, FALLBACK_ROUTE)
        self.assertTrue(result.quality_issues)
        self.fallback.extract.assert_called_once_with(ROAD)
        self.selector.assert_called_once_with(self.request)

    def test_transient_radar_read_is_retried_without_repeating_primary_or_selector(self):
        self.primary.extract.return_value = video_state(confidence=0, flow=False, queue=False)
        self.fallback.extract.side_effect = [ConnectionError("radar timeout"), radar_state()]
        result = self.graph.execute_legacy(self.request)
        self.assertEqual(result.route, FALLBACK_ROUTE)
        self.primary.extract.assert_called_once_with(ROAD)
        self.assertEqual(self.fallback.extract.call_count, 2)
        self.selector.assert_called_once_with(self.request)

    def test_exhausted_read_errors_of_both_experts_still_select_once(self):
        self.primary.extract.side_effect = TimeoutError("video timeout")
        self.fallback.extract.side_effect = ConnectionError("radar disconnected")
        result = self.graph.execute_legacy(self.request)
        self.assertEqual(result.route, FALLBACK_ROUTE)
        self.assertIsNone(result.primary)
        self.assertIsNone(result.fallback)
        self.assertTrue(result.quality_issues)
        self.assertIs(result.selection, self.raw_selection)
        self.assertEqual(self.primary.extract.call_count, 2)
        self.assertEqual(self.fallback.extract.call_count, 2)
        self.selector.assert_called_once_with(self.request)

    def test_expert_contract_errors_degrade_without_retry(self):
        for error in (ExpertContractError("invalid source"),
                      ExpertContractError("invalid intersection")):
            with self.subTest(error=error):
                self.primary.extract.reset_mock()
                self.selector.reset_mock()
                self.primary.extract.side_effect = error
                result = self.graph.execute_legacy(self.request)
                self.primary.extract.assert_called_once_with(ROAD)
                self.assertTrue(result.used_fallback)
                self.assertTrue(result.quality_issues)
                self.selector.assert_called_once_with(self.request)

    def test_unknown_expert_errors_propagate_unchanged_without_selection(self):
        for error in (RuntimeError("expert bug"), KeyError("unexpected missing key"),
                      ValueError("unexpected algorithm value"),
                      TypeError("unexpected algorithm type")):
            with self.subTest(error=error):
                self.primary.extract.reset_mock()
                self.primary.extract.side_effect = error
                with self.assertRaises(type(error)) as raised:
                    self.graph.execute_legacy(self.request)
                self.assertIs(raised.exception, error)
                self.primary.extract.assert_called_once_with(ROAD)
        self.selector.assert_not_called()

    def test_expert_programming_type_error_is_not_treated_as_contract_failure(self):
        def broken_extract(road):
            return 1 + None

        self.primary.extract.side_effect = broken_extract
        with self.assertRaises(TypeError):
            self.graph.execute_legacy(self.request)
        self.primary.extract.assert_called_once_with(ROAD)
        self.fallback.extract.assert_not_called()
        self.selector.assert_not_called()

    def test_selector_errors_propagate_unchanged_and_never_retry(self):
        for error in (TimeoutError("selector timeout"), ConnectionError("selector disconnected"),
                      RuntimeError("legacy failure")):
            with self.subTest(error=error):
                self.selector.reset_mock()
                self.selector.side_effect = error
                with self.assertRaises(type(error)) as raised:
                    self.graph.execute_legacy(self.request)
                self.assertIs(raised.exception, error)
                self.selector.assert_called_once_with(self.request)

    def test_nodes_execute_in_declared_order(self):
        events = []

        def primary(road):
            events.append("primary_expert")
            return video_state(road, confidence=0, flow=False, queue=False)

        def fallback(road):
            events.append("fallback_expert")
            return radar_state(road)

        def select(request):
            events.append("control_policy")
            return self.raw_selection

        self.primary.extract.side_effect = primary
        self.fallback.extract.side_effect = fallback
        self.selector.side_effect = select
        result = self.graph.execute_legacy(self.request)
        self.assertEqual(events, ["primary_expert", "fallback_expert", "control_policy"])
        self.assertEqual(result.route, FALLBACK_ROUTE)

    def test_next_run_does_not_reuse_previous_radar_or_quality_state(self):
        self.primary.extract.side_effect = ExpertContractError("first run malformed")
        first = self.graph.execute_legacy(self.request)
        self.assertTrue(first.used_fallback)
        self.assertTrue(first.quality_issues)
        self.primary.extract.side_effect = None
        self.primary.extract.return_value = video_state()
        second = self.graph.execute_legacy(self.request)
        self.assertFalse(second.used_fallback)
        self.assertIsNone(second.fallback)
        self.assertEqual(second.route, DIRECT_ROUTE)
        self.assertFalse(second.quality_issues)
        self.fallback.extract.assert_called_once_with(ROAD)

    def test_graph_and_read_retries_do_not_consume_business_random_state(self):
        for retry_errors in (False, True):
            with self.subTest(retry_errors=retry_errors):
                if retry_errors:
                    self.primary.extract.side_effect = TimeoutError("video timeout")
                    self.fallback.extract.side_effect = ConnectionError("radar disconnected")
                before = random.getstate()
                result = self.graph.execute_legacy(self.request)
                self.assertEqual(random.getstate(), before)
                self.assertEqual(result.route, FALLBACK_ROUTE if retry_errors else DIRECT_ROUTE)
        self.assertEqual(self.selector.call_count, 2)

    def test_selector_consumes_exactly_its_business_random_sequence(self):
        previous_state = random.getstate()
        expected = random.Random(5182)
        initial_state = expected.getstate()
        expected_values = [expected.random() for _ in range(3)]

        def select(request):
            plan, coordinate, model, experience = selection(request.cross_id)
            return plan, coordinate, [random.random()], experience

        self.selector.side_effect = select
        try:
            random.setstate(initial_state)
            results = [self.graph.execute_legacy(self.request) for _ in range(3)]
            self.assertEqual([result.selection[2][0] for result in results], expected_values)
            self.assertEqual(random.getstate(), expected.getstate())
        finally:
            random.setstate(previous_state)
        self.assertEqual(self.selector.call_count, 3)

    def test_concurrent_graph_calls_consume_only_selector_random_draws(self):
        previous_state = random.getstate()
        expected = random.Random(7724)
        initial_state = expected.getstate()
        requests = [IntersectionControlRequest(cross_id=str(i), current_time=1)
                    for i in range(1, 33)]
        expected_values = [expected.random() for _ in requests]

        def select(request):
            plan, coordinate, model, experience = selection(request.cross_id)
            return plan, coordinate, [random.random()], experience

        self.primary.extract.side_effect = lambda road: video_state(road)
        self.selector.side_effect = select
        try:
            random.setstate(initial_state)
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(self.graph.execute_legacy, requests))
            self.assertEqual(sorted(result.selection[2][0] for result in results),
                             sorted(expected_values))
            self.assertEqual(random.getstate(), expected.getstate())
        finally:
            random.setstate(previous_state)
        self.assertEqual(self.selector.call_count, len(requests))

    def test_shared_graph_keeps_concurrent_requests_and_diagnostics_separate(self):
        def primary(road):
            sufficient = int(road) % 2 == 0
            return video_state(road, confidence=int(sufficient), flow=sufficient, queue=sufficient)

        self.primary.extract.side_effect = primary
        self.fallback.extract.side_effect = radar_state
        self.selector.side_effect = lambda request: selection(request.cross_id)
        requests = [IntersectionControlRequest(cross_id=str(i), current_time=1)
                    for i in range(1, 33)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self.graph.execute_legacy, requests))
        for request, result in zip(requests, results):
            with self.subTest(road=request.cross_id):
                fallback = int(request.cross_id) % 2 == 1
                self.assertEqual(result.used_fallback, fallback)
                self.assertEqual(result.route, FALLBACK_ROUTE if fallback else DIRECT_ROUTE)
                self.assertEqual(result.candidate.intersection_id, request.cross_id)
                self.assertEqual(result.selection[1]["road"], request.cross_id)
                self.assertEqual(result.selection[2], [request.cross_id])
                self.assertEqual(result.selection[3]["experience"], request.cross_id)
                self.assertEqual(result.primary.observation.cross_id, request.cross_id)
                if fallback:
                    self.assertEqual(result.fallback.observation.cross_id, request.cross_id)
                else:
                    self.assertIsNone(result.fallback)
        self.assertEqual(self.selector.call_count, len(requests))


if __name__ == "__main__":
    unittest.main()
