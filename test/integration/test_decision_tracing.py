"""固定配时的逐轮追踪、业务失败、并发隔离与黄金回放。"""

import json
import io
import math
import random
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import Lambdas
from control.policies import BaselineController
from datahub import TrafficDataHub
from runtime.tracing import DecisionTrace
from lib.road_groups import road_group
from test import test_datahub_integration as hub_tests
from test import test_decision_pipeline as pipeline_tests
from test.fixtures.v2_baseline_controller import FIXTURE, compact_round, full_replay
from test.test_model_gateway_integration import model_application
from test.unit.test_safety_engine import engine


PLAN = [25, 30, 0, 0, 0, 0, 0, 0, 0, 1]


def records(logger):
    result = []
    for call in logger.info.call_args_list:
        if call.args[0] == "%s":
            record = json.loads(call.args[1])
            if record.get("event") == "aitc.decision":
                result.append(record)
    return result


class DecisionTracingIntegrationTest(unittest.TestCase):
    def pipeline(self, *, selector=None):
        pipeline, _hub = hub_tests.DataHubIntegrationTest()._make_pipeline(
            selector or (lambda request: (list(PLAN), {}, [], {})),
        )
        logger = Mock()
        pipeline.logger = logger
        pipeline.safety_engine = engine()
        return pipeline, logger

    def test_disabled_model_record_contains_actual_snapshot_candidate_and_final(self):
        pipeline, logger = self.pipeline()
        result = pipeline.run_once()
        record, = records(logger)
        self.assertEqual(record["status"], "published")
        self.assertEqual(record["publication_target"], "result_warehouse")
        self.assertEqual(record["intersection_id"], "100")
        self.assertEqual(record["traffic_snapshot"]["cross_id"], "100")
        self.assertEqual(record["input_timestamp"], record["traffic_snapshot"]["current_time"])
        self.assertFalse(record["llm_participated"])
        self.assertEqual(record["model_calls"], 0)
        self.assertEqual(record["candidate_legacy"], PLAN)
        self.assertEqual(record["final_legacy"], result[0]["action"])
        self.assertEqual(record["control_policy"], "BaselineController")
        self.assertEqual(record["expert_calls"], [])
        self.assertEqual(record["route"], ["control_policy"])
        self.assertTrue(record["safety_report"]["safe"])
        for stage in ("control", "coordination", "safety", "format", "publish"):
            self.assertGreaterEqual(record["stage_latency_ms"][stage], 0)

    def test_trace_records_selector_failure_before_candidate(self):
        pipeline, logger = self.pipeline(selector=Mock(side_effect=RuntimeError("selector failed")))
        pipeline.run_once()
        record, = records(logger)
        self.assertEqual(record["errors"][0]["stage"], "control")
        self.assertFalse(record["llm_participated"])
        self.assertEqual(record["expert_calls"], [])
        self.assertEqual(record["route"], ["control_policy"])
        self.assertIsNone(record["candidate_signal_plan"])
        self.assertEqual(record["status"], "published")
        self.assertEqual(record["final_legacy"], [0] * 10)

    def test_experience_write_failure_preserves_computed_candidate_in_trace(self):
        pipeline, logger = self.pipeline()
        pipeline.writer.write_experience = Mock(side_effect=OSError("disk full"))
        pipeline.run_once()
        record, = records(logger)
        self.assertEqual(record["candidate_legacy"], PLAN)
        self.assertEqual(record["final_legacy"], [0] * 10)
        self.assertEqual(record["errors"][0]["stage"], "experience_write")

    def test_coordination_failure_emits_failure_and_retains_previous_warehouse(self):
        pipeline, logger = self.pipeline()
        error = RuntimeError("coordination failed")
        pipeline.coordinate = Mock(side_effect=error)
        pipeline.result_warehouse.replace([{"id": "previous"}])
        with self.assertRaises(RuntimeError) as raised:
            pipeline.run_once()
        record, = records(logger)
        self.assertIs(raised.exception, error)
        self.assertEqual(record["status"], "batch_failed")
        self.assertEqual(record["errors"][-1]["stage"], "coordination")
        self.assertIsNone(record["final_signal_plan"])
        self.assertEqual(pipeline.result_warehouse.snapshot(), [{"id": "previous"}])

    def test_format_failure_retains_proposed_final_but_does_not_claim_publication(self):
        pipeline, logger = self.pipeline()
        pipeline.select_data_to_send = Mock(side_effect=ValueError("invalid model info"))
        with self.assertRaises(ValueError):
            pipeline.run_once()
        record, = records(logger)
        self.assertEqual(record["final_legacy"], PLAN)
        self.assertEqual(record["status"], "batch_failed")
        self.assertEqual(record["errors"][-1]["stage"], "format")

    def test_safety_fallback_records_different_candidate_and_final(self):
        pipeline, logger = self.pipeline()

        def corrupt(action, *_args):
            action["100"][2] = 15
            action["100"][1] = 0
            return action

        pipeline.coordinate = corrupt
        pipeline.run_once()
        record, = records(logger)
        self.assertEqual(record["candidate_legacy"], PLAN)
        self.assertEqual(record["safety_report"]["fallback_source"], "baseline_candidate")
        self.assertIn("safety:phase_2_after_zero_terminator", record["fallback_reason"])

    def test_no_datahub_legacy_constructor_still_emits_input_and_plan_evidence(self):
        pipeline = pipeline_tests.PeriodicDecisionPipelineTest()._make_pipeline(logger=Mock())
        pipeline.run_once()
        record, = records(pipeline.logger)
        self.assertEqual(record["snapshot_status"], "not_captured")
        self.assertIsNone(record["traffic_snapshot"])
        self.assertEqual(record["input_request"]["cross_id"], "100")

    def test_failed_snapshot_capture_keeps_legacy_input_and_selector_execution(self):
        pipeline, logger = self.pipeline()
        pipeline.datahub.capture = Mock(return_value=None)
        selector = Mock(return_value=(list(PLAN), {}, [], {}))
        pipeline.dqn_select = selector
        result = pipeline.run_once()
        record, = records(logger)
        selector.assert_called_once()
        self.assertEqual(result[0]["action"], PLAN)
        self.assertEqual(record["snapshot_status"], "unavailable")
        self.assertIsNone(record["traffic_snapshot"])
        self.assertEqual(record["input_request"]["cross_id"], "100")

    def test_opaque_and_nonfinite_observations_do_not_change_the_computed_plan(self):
        pipeline, logger = self.pipeline()
        pipeline.flow_predictor.get_current_flow_prediction = lambda: {"100": {"value": object(), "flow": math.nan}}
        result = pipeline.run_once()
        record, = records(logger)
        self.assertEqual(result[0]["action"], PLAN)
        batch = next(json.loads(call.args[1]) for call in logger.info.call_args_list
                     if call.args[0] == "%s"
                     and json.loads(call.args[1]).get("event") == "aitc.decision_batch")
        self.assertEqual(record["input_context_batch_id"], batch["batch_id"])
        observed = batch["shared_input"]["predicted_flow"]["100"]
        self.assertEqual(observed["value"]["trace_omitted"], "unsupported_type")
        self.assertEqual(observed["flow"]["trace_omitted"], "non_finite_number")

    def test_trace_logging_failure_does_not_change_published_batch_or_selector_count(self):
        selector = Mock(return_value=(list(PLAN), {}, [], {}))
        pipeline, logger = self.pipeline(selector=selector)

        def log(template, *_args, **_kwargs):
            if template == "%s":
                raise OSError("trace sink unavailable")

        logger.info.side_effect = log
        with patch("runtime.tracing.sys.stderr", new_callable=io.StringIO) as stderr:
            result = pipeline.run_once()
        self.assertEqual(result[0]["action"], PLAN)
        self.assertEqual(pipeline.result_warehouse.snapshot(), result)
        selector.assert_called_once()
        self.assertIn("Decision trace logging failed", stderr.getvalue())

    def test_worker_failure_before_request_build_is_not_missing_from_trace(self):
        pipeline, logger = self.pipeline()
        with patch.object(pipeline.lambdas, "intersection_flow_lambda", {}):
            with self.assertRaises(KeyError):
                pipeline.run_once()
        record, = records(logger)
        self.assertEqual(record["status"], "batch_failed")
        self.assertTrue(any(error["stage"] == "worker" for error in record["errors"]))
        self.assertIsNone(record["input_timestamp"])

    def test_concurrent_workers_keep_road_identity_and_candidate_isolation(self):
        base = pipeline_tests._Lambdas
        lambdas = SimpleNamespace(
            intersection_list=["100", "200"], map_lambda={"100": {}, "200": {}},
            intersection_flow_lambda={"100": [1, 2, 3, 4], "200": [5, 6, 7, 8]},
            max_lengths_lambda={"100": {}, "200": {}}, intersection_result_lambda=base.intersection_result_lambda,
        )
        pipeline = pipeline_tests.PeriodicDecisionPipelineTest()._make_pipeline(logger=Mock(), worker_count=2)
        pipeline.lambdas = lambdas
        pipeline.data_processor.radar_event = lambda *_args: {"100": {}, "200": {}}
        pipeline.dqn_select = lambda request: ([int(request.cross_id)] + [0] * 8 + [1], {}, [], {})
        pipeline.run_once()
        seen = records(pipeline.logger)
        self.assertEqual(len({item["batch_id"] for item in seen}), 1)
        self.assertEqual(len({item["trace_id"] for item in seen}), 2)
        for item in seen:
            self.assertEqual(item["input_request"]["cross_id"], item["intersection_id"])
            self.assertEqual(item["candidate_legacy"][0], int(item["intersection_id"]))

    def test_two_round_control_replay_preserves_golden_results_and_rng(self):
        hub = TrafficDataHub(lambdas_module=Lambdas)
        controller = BaselineController()
        traces = {}
        logger = Mock()
        before = random.getstate()

        def selector(request):
            snapshot = hub.capture(request)
            trace = DecisionTrace(batch_id=f"golden-{request.current_time}", intersection_id=request.cross_id,
                                  control_policy="BaselineController")
            trace.capture_input(request, snapshot, has_datahub=True)
            trace.route = ["control_policy"]
            selection = controller.select_legacy(request)
            trace.capture_plan(selection[0])
            traces[(request.current_time, request.cross_id)] = trace
            return selection

        actual = full_replay(selector)
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for index, result in enumerate(actual):
            self.assertEqual(compact_round(result), golden["rounds"][index])
            for road, plan in result["after_phase_check"].items():
                trace = traces[(result["timestamp"], road)]
                trace.capture_plan(plan, final=True)
                trace.status = "published"
                trace.emit(logger)
        self.assertEqual(len(records(logger)), 470)
        self.assertEqual(len({item["trace_id"] for item in records(logger)}), 470)
        self.assertEqual(random.getstate(), before)

    def test_production_application_emits_one_record_per_road(self):
        with model_application("disabled") as app:
            pipeline = app.decision_pipeline
            pipeline.logger = Mock()
            pipeline.worker_count = 1
            with patch.object(pipeline, "coordinate", side_effect=lambda actions, *_args: actions), patch.object(
                pipeline, "dqn_select", side_effect=lambda request: (list(PLAN), {}, [], {}),
            ):
                pipeline.run_once()
            seen = records(pipeline.logger)
            self.assertEqual(len(seen), 235)
            self.assertEqual({item["intersection_id"] for item in seen}, set(Lambdas.intersection_list))
            self.assertTrue(all(item["status"] == "published" for item in seen))
            batches = [json.loads(call.args[1]) for call in pipeline.logger.info.call_args_list
                       if call.args[0] == "%s" and json.loads(call.args[1]).get("event") == "aitc.decision_batch"]
            self.assertEqual(len(batches), 1)
            self.assertEqual(set(batches[0]["shared_input"]),
                             {"previous_coordinate", "predicted_flow", "predicted_queue"})
            for item in seen:
                self.assertEqual(item["schema_version"], 2)
                self.assertEqual(item["input_context_batch_id"], batches[0]["batch_id"])
                self.assertEqual(item["input_detail"],
                                 "full" if road_group(item["intersection_id"]) in {"19", "49"} else "summary")
                self.assertNotIn("previous_coordinate", item["traffic_snapshot"])


if __name__ == "__main__":
    unittest.main()
