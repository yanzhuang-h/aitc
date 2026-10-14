"""最终闭环验收：真实接入、专家/模型、原算法、安全、追踪、仓库和 TCP。"""

import copy
import json
import unittest
from unittest.mock import patch

import Lambdas
from app.infrastructure.llm import MockProvider, ModelResponse
from agent.control_tools import snapshot_summary
from infra.data.classifier import DataKind, DataSource
from runtime.tracing import DecisionTrace
from test.fixtures.v2_acceptance import (
    RADAR_INTERSECTION, VIDEO_INTERSECTION, acceptance_application, broadcast_results,
    model_endpoint, send_radar_http, send_tcp_inputs, source_payloads, tcp_channel,
)
from test.fixtures.v2_baseline_controller import FIXED_TIME, FIXTURE, compact_round, full_replay, isolated_runtime
from test.integration.test_decision_tracing import records


class ReviewScript(MockProvider):
    """依据宿主阶段给出固定结构化动作，不产生观测或相位时间。"""

    def invoke(self, request):
        context = json.loads(request.messages[-1].content)
        command = ({"tool": "run_control_policy", "arguments": {}} if context["phase"] == "planner"
                   else {"tool": "review_signal_plan", "arguments": {"decision": "WARN", "reason": "Keep baseline candidate"}})
        return ModelResponse(content=json.dumps(command))


class V2AcceptanceTest(unittest.TestCase):
    def feed(self, app, client, *, video=True, queue=True, radar=False):
        payloads = source_payloads(FIXED_TIME)
        tcp = [payload for kind, source, payload in payloads if source == DataSource.TCP
               and video and (queue or kind != DataKind.QUEUE)]
        if tcp:
            send_tcp_inputs(app, client, tcp)
        if radar:
            send_radar_http(app, payloads[2][2])

    def run_wire_case(self, *, provider="disabled", base_url="", timeout=1.0, video=True, queue=True, radar=False, unavailable_snapshot=False):
        with isolated_runtime(), acceptance_application(provider=provider, base_url=base_url, timeout=timeout) as (app, logger), tcp_channel(app) as client:
            self.feed(app, client, video=video, queue=queue, radar=radar)
            if unavailable_snapshot:
                with patch.object(app.datahub, "capture", return_value=None):
                    result = app.decision_pipeline.run_once()
            else:
                result = app.decision_pipeline.run_once()
            frames, received = broadcast_results(app, client, len(result))
            self.assertEqual(received, result)
            self.assertEqual(received, app.decision_pipeline.result_warehouse.snapshot())
            self.assertEqual(len(result), 186)
            self.assertTrue(all(b'"trace_id"' not in frame for frame in frames))
            trace_records = records(logger)
            self.assertEqual(len(trace_records), 186)
            return result, trace_records

    def test_no_llm_video_only_reaches_original_tcp_output(self):
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", side_effect=AssertionError("no LLM mode must not use model network")) as network:
            result, traced = self.run_wire_case()
        network.assert_not_called()
        record = next(item for item in traced if item["intersection_id"] == VIDEO_INTERSECTION)
        self.assertEqual([item["source"] for item in record["expert_calls"]], ["video"])
        self.assertFalse(record["llm_participated"])
        self.assertEqual(record["traffic_snapshot"]["traffic_vector"], [1, 0, 0, 0])
        self.assertIsNone(record["traffic_snapshot"]["predicted_flow"])
        self.assertIsNone(record["traffic_snapshot"]["predicted_queue"])
        payload = next(item for item in result if item["additional"]["tlLogic"]["id"] == VIDEO_INTERSECTION)
        self.assertEqual(record["final_signal_plan"]["program_id"], payload["additional"]["tlLogic"]["programID"])

    def test_cold_start_snapshot_fix_preserves_previous_legacy_outputs(self):
        old, old_trace = self.run_wire_case(unavailable_snapshot=True)
        corrected, corrected_trace = self.run_wire_case()
        self.assertEqual(corrected, old)
        self.assertTrue(all(item["snapshot_status"] == "unavailable" for item in old_trace))
        self.assertTrue(all(item["snapshot_status"] == "captured" for item in corrected_trace))

    def test_missing_video_queue_and_http_radar_take_real_fallback_path(self):
        _result, traced = self.run_wire_case(queue=False, radar=True)
        video = next(item for item in traced if item["intersection_id"] == VIDEO_INTERSECTION)
        radar = next(item for item in traced if item["intersection_id"] == RADAR_INTERSECTION)
        self.assertEqual([item["source"] for item in video["expert_calls"]], ["video", "radar"])
        self.assertIn("queue_map", video["expert_calls"][0]["missing_fields"])
        self.assertEqual(radar["expert_calls"][1]["confidence"], 1)
        self.assertTrue(radar["traffic_snapshot"]["radar_map"])

    def test_real_qwen_compatible_http_review_preserves_disabled_control(self):
        expected, _traces = self.run_wire_case()
        with model_endpoint() as (url, requests):
            actual, traced = self.run_wire_case(provider="qwen", base_url=url)
        self.assertEqual(actual, expected)
        self.assertTrue(requests)
        self.assertTrue(all(item["path"] == "/v1/chat/completions" for item in requests))
        self.assertTrue(any(item["review"] is not None for item in traced))
        fast = next(item for item in traced if item["intersection_id"] == VIDEO_INTERSECTION)
        self.assertFalse(fast["llm_participated"])
        self.assertTrue(all(item["body"]["chat_template_kwargs"] == {"enable_thinking": False} for item in requests))

    def test_real_deepseek_style_http_review_preserves_disabled_control(self):
        expected, _traces = self.run_wire_case()
        with model_endpoint() as (url, requests):
            actual, traced = self.run_wire_case(provider="deepseek", base_url=url)
        self.assertEqual(actual, expected)
        self.assertTrue(any(item["model_provider"] == "deepseek" for item in traced))
        self.assertTrue(all(item["authorization"] == "Bearer acceptance-test-key" for item in requests))
        self.assertTrue(all(item["body"]["thinking"] == {"type": "disabled"} for item in requests))
        self.assertTrue(all("chat_template_kwargs" not in item["body"] for item in requests))

    def test_real_http_503_preserves_control_and_cools_subsequent_intersections(self):
        expected, _traces = self.run_wire_case()
        with model_endpoint("unavailable") as (url, requests):
            actual, traced = self.run_wire_case(provider="qwen", base_url=url)
        self.assertEqual(actual, expected)
        self.assertEqual(len(requests), 1)
        self.assertTrue(any(error["type"] == "ModelUnavailableError" for item in traced for error in item["errors"]))
        self.assertTrue(any(item["model_reason"] == "model_cooldown" for item in traced))

    def test_real_socket_timeout_preserves_control_and_is_traced(self):
        expected, _traces = self.run_wire_case()
        with model_endpoint("timeout") as (url, requests):
            actual, traced = self.run_wire_case(provider="deepseek", base_url=url, timeout=0.03)
        self.assertEqual(actual, expected)
        self.assertEqual(len(requests), 1)
        self.assertTrue(any(error["type"] == "ModelTimeoutError" for item in traced for error in item["errors"]))

    def test_illegal_remote_control_action_cannot_change_original_plans(self):
        expected, _traces = self.run_wire_case()
        with model_endpoint("invalid_action") as (url, requests):
            actual, traced = self.run_wire_case(provider="qwen", base_url=url)
        self.assertEqual(actual, expected)
        self.assertTrue(requests)
        self.assertTrue(any("model:invalid_action" in item["fallback_reason"] for item in traced))
        self.assertTrue(all(item["review"] is None for item in traced))

    def test_model_accept_does_not_bypass_final_safety_or_tcp_fallback(self):
        with isolated_runtime(), model_endpoint() as (url, _requests), acceptance_application(provider="deepseek", base_url=url) as (app, logger), tcp_channel(app) as client:
            self.feed(app, client, video=False, radar=True)
            coordinate = app.decision_pipeline.coordinate

            def corrupt(*args):
                plans = coordinate(*args)
                plans[VIDEO_INTERSECTION][8] = 7
                return plans

            app.decision_pipeline.coordinate = corrupt
            result = app.decision_pipeline.run_once()
            _frames, received = broadcast_results(app, client, len(result))
            self.assertEqual(received, result)
            trace = next(item for item in records(logger) if item["intersection_id"] == VIDEO_INTERSECTION)
            self.assertEqual(trace["review"]["decision"], "ACCEPT")
            # 冷启动的原候选是无动作标记，安全门沿用当前小时的真实时刻表。
            self.assertEqual(trace["safety_report"]["fallback_source"], "timetable")
            self.assertTrue(trace["safety_report"]["safe"])
            self.assertEqual(trace["final_legacy"][8], 0)
            self.assertIn("safety:reserved_slot_must_be_zero", trace["fallback_reason"])

    def test_real_ingestion_history_is_bounded_and_cannot_cross_intersections(self):
        with isolated_runtime(), acceptance_application() as (app, logger):
            for index in range(3):
                with patch("time.time", return_value=FIXED_TIME + index):
                    app.tcp_server.ingestor.ingest_tcp([payload for _kind, source, payload in source_payloads(FIXED_TIME + index) if source == DataSource.TCP])
                    app.decision_pipeline.run_once()
            history = app.datahub.history(VIDEO_INTERSECTION)
            self.assertEqual([item.current_time for item in history], [FIXED_TIME + 1, FIXED_TIME + 2])
            self.assertTrue(all(item.cross_id == VIDEO_INTERSECTION for item in history))
            self.assertIsNone(history[-1].predicted_flow)
            self.assertEqual(snapshot_summary(history[-1])["missing_prediction_fields"], ["predicted_flow", "predicted_queue"])
            other = app.datahub.history(RADAR_INTERSECTION)
            self.assertTrue(all(item.cross_id == RADAR_INTERSECTION for item in other))
            self.assertEqual(len(records(logger)), 558)

    def test_combined_graph_safety_tracing_and_tcp_match_frozen_two_round_baseline(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for provider in ("disabled", "mock"):
            with self.subTest(provider=provider), acceptance_application(provider=provider) as (app, logger):
                if provider == "mock":
                    app.model_gateway.provider = ReviewScript()
                traces = {}
                gate = app.decision_pipeline.safety_engine

                def select(request):
                    snapshot = app.datahub.capture(request)
                    trace = DecisionTrace(batch_id=f"acceptance-{request.current_time}", intersection_id=request.cross_id, control_policy="BaselineController")
                    trace.capture_input(request, snapshot, has_datahub=True)
                    decision = app.decision_graph.execute_legacy(request, snapshot=snapshot, trace_id=trace.trace_id, expert_calls=trace.expert_calls)
                    trace.capture_graph(decision, provider=provider)
                    trace.capture_plan(decision.selection[0])
                    traces[request.cross_id] = trace
                    return decision.selection

                def finalize(plans):
                    final, reports = gate.finalize(plans)
                    for road, trace in traces.items():
                        trace.capture_plan(final[road], final=True)
                        trace.safety_report = copy.deepcopy(reports[road])
                        trace.emit(logger)
                    return final, {road: {key: report[key] for key in ("check_status", "msg", "modifications")}
                                   for road, report in reports.items()}

                with patch("test.fixtures.v2_baseline_controller.phase_checker.phase_check", finalize):
                    actual = full_replay(select, app.decision_pipeline.coordinate)
                for index, result in enumerate(actual):
                    self.assertEqual(compact_round(result), golden["rounds"][index])
                self.assertEqual(len(records(logger)), 372)
                self.assertEqual(len({item["trace_id"] for item in records(logger)}), 372)
                self.assertTrue(all(item["llm_participated"] == (provider == "mock") for item in records(logger)))


if __name__ == "__main__":
    unittest.main()
