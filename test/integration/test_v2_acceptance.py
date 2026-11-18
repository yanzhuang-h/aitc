"""固定配时闭环验收：真实接入、原算法、安全、追踪、仓库和 TCP。"""

import copy
import json
import unittest
from unittest.mock import patch

from agents.experts import RadarExpert, VideoExpert

from agents.control_tools import snapshot_summary
from datahub.classifier import DataKind, DataSource
from runtime.tracing import DecisionTrace
from test.fixtures.v2_acceptance import (
    RADAR_INTERSECTION, VIDEO_INTERSECTION, acceptance_application, broadcast_results,
    send_radar_http, send_tcp_inputs, source_payloads, tcp_channel,
)
from test.fixtures.v2_baseline_controller import FIXED_TIME, FIXTURE, compact_round, full_replay, isolated_runtime
from test.integration.test_decision_tracing import records


class V2AcceptanceTest(unittest.TestCase):
    def feed(self, app, client, *, video=True, radar=False):
        payloads = source_payloads(FIXED_TIME)
        tcp = [payload for _kind, source, payload in payloads if source == DataSource.TCP
               and video]
        if tcp:
            send_tcp_inputs(app, client, tcp)
        if radar:
            send_radar_http(app, payloads[2][2])

    def run_wire_case(self, *, unavailable_snapshot=False):
        with isolated_runtime(), acceptance_application() as (app, logger), tcp_channel(app) as client:
            self.feed(app, client)
            if unavailable_snapshot:
                with patch.object(app.datahub, "capture", return_value=None):
                    result = app.decision_pipeline.run_once()
            else:
                result = app.decision_pipeline.run_once()
            frames, received = broadcast_results(app, client, len(result))
            self.assertEqual(received, result)
            self.assertEqual(received, app.decision_pipeline.result_warehouse.snapshot())
            self.assertEqual(len(result), 235)
            self.assertTrue(all(b'"trace_id"' not in frame for frame in frames))
            trace_records = records(logger)
            self.assertEqual(len(trace_records), 235)
            return result, trace_records

    def test_no_llm_video_only_reaches_original_tcp_output(self):
        with patch("models.openai_compatible.request.urlopen", side_effect=AssertionError("no LLM mode must not use model network")) as network, patch.object(
            VideoExpert, "extract", side_effect=AssertionError("fixed control must not repeat video aggregation"),
        ) as video, patch.object(
            RadarExpert, "extract", side_effect=AssertionError("fixed control must not repeat radar aggregation"),
        ) as radar:
            result, traced = self.run_wire_case()
        network.assert_not_called()
        video.assert_not_called()
        radar.assert_not_called()
        record = next(item for item in traced if item["intersection_id"] == VIDEO_INTERSECTION)
        self.assertEqual(record["expert_calls"], [])
        self.assertEqual(record["route"], ["control_policy"])
        self.assertTrue(record["safety_report"]["safe"])
        self.assertFalse(record["llm_participated"])
        self.assertEqual(record["traffic_snapshot"]["traffic_vector"], [1, 0, 0, 0])
        self.assertEqual(record["input_context_batch_id"], record["batch_id"])
        self.assertNotIn("predicted_flow", record["traffic_snapshot"])
        self.assertNotIn("predicted_queue", record["traffic_snapshot"])
        payload = next(item for item in result if item["additional"]["tlLogic"]["id"] == VIDEO_INTERSECTION)
        self.assertEqual(record["final_signal_plan"]["program_id"], payload["additional"]["tlLogic"]["programID"])

    def test_fixed_control_still_applies_final_safety(self):
        with isolated_runtime(), acceptance_application() as (app, logger):
            coordinate = app.decision_pipeline.coordinate

            def corrupt(*args):
                plans = coordinate(*args)
                plans[VIDEO_INTERSECTION][8] = 7
                return plans

            app.decision_pipeline.coordinate = corrupt
            result = app.decision_pipeline.run_once()
            self.assertEqual(result, app.decision_pipeline.result_warehouse.snapshot())
            trace = next(item for item in records(logger) if item["intersection_id"] == VIDEO_INTERSECTION)
            self.assertEqual(trace["route"], ["control_policy"])
            self.assertTrue(trace["safety_report"]["safe"])
            self.assertEqual(trace["final_legacy"][8], 0)
            self.assertIn("safety:reserved_slot_must_be_zero", trace["fallback_reason"])

    def test_cold_start_snapshot_fix_preserves_previous_legacy_outputs(self):
        old, old_trace = self.run_wire_case(unavailable_snapshot=True)
        corrected, corrected_trace = self.run_wire_case()
        self.assertEqual(corrected, old)
        self.assertTrue(all(item["snapshot_status"] == "unavailable" for item in old_trace))
        self.assertTrue(all(item["snapshot_status"] == "captured" for item in corrected_trace))

    def test_cold_start_safety_fallback_reaches_tcp_with_http_model_enabled(self):
        with isolated_runtime(), acceptance_application(provider="mock") as (app, logger), tcp_channel(app) as client:
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
            self.assertFalse(trace["llm_participated"])
            self.assertEqual(trace["route"], ["control_policy"])
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
            self.assertEqual(len(records(logger)), 705)

    def test_safety_tracing_and_tcp_match_frozen_two_round_baseline(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for provider in ("disabled", "mock"):
            with self.subTest(provider=provider), acceptance_application(provider=provider) as (app, logger):
                traces = {}
                gate = app.decision_pipeline.safety_engine

                def select(request):
                    snapshot = app.datahub.capture(request)
                    trace = DecisionTrace(batch_id=f"acceptance-{request.current_time}", intersection_id=request.cross_id, control_policy="BaselineController")
                    trace.capture_input(request, snapshot, has_datahub=True)
                    trace.route = ["control_policy"]
                    selection = app.decision_pipeline.dqn_select(request)
                    trace.capture_plan(selection[0])
                    traces[request.cross_id] = trace
                    return selection

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
                self.assertEqual(len(records(logger)), 470)
                self.assertEqual(len({item["trace_id"] for item in records(logger)}), 470)
                self.assertTrue(all(not item["llm_participated"] for item in records(logger)))


if __name__ == "__main__":
    unittest.main()
