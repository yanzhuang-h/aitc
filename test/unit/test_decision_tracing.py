"""严格追踪边界、完整快照、JSON 异常值和算法随机数隔离。"""

import io
import json
import math
import random
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from datahub.traffic_adapters import snapshot_from_legacy
from lib.control_functions.types import IntersectionControlRequest
from runtime.tracing import DecisionTrace, trace_stage, trace_value


class DecisionTracingTest(unittest.TestCase):
    def trace(self):
        return DecisionTrace(batch_id="batch", intersection_id="100", control_policy="BaselineController")

    def test_schema_rejects_coerced_identity_status_and_nonfinite_latencies(self):
        for invalid in ({"intersection_id": 100}, {"status": "sent"}, {"latency_ms": math.nan},
                        {"model_calls": True}, {"llm_participated": "false"}, {"unexpected": True}):
            values = {"batch_id": "batch", "intersection_id": "100", "control_policy": "BaselineController"}
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                DecisionTrace(**(values | invalid))

    def test_ids_are_unique_and_do_not_advance_algorithm_random_generator(self):
        before = random.getstate()
        traces = [self.trace() for _ in range(30)]
        self.assertEqual(len({trace.trace_id for trace in traces}), 30)
        self.assertEqual(random.getstate(), before)

    def test_actual_full_snapshot_is_detached_before_selector_mutation(self):
        request = IntersectionControlRequest(
            cross_id="100", current_time=123,
            flow_map={123: {"items": list(range(30))}},
            predicted_flow={"100": {"flow": 5}, "200": {"flow": 9}},
            previous_coordinate={"100": {"start": 7}, "200": {"start": 8}},
        )
        snapshot = snapshot_from_legacy(request)
        trace = self.trace()
        trace.capture_input(request, snapshot, has_datahub=True)
        request.flow_map[123]["items"].clear()
        self.assertEqual(trace.traffic_snapshot["flow_map"]["123"]["items"], list(range(30)))
        self.assertEqual(trace.traffic_snapshot["predicted_flow"]["200"], {"flow": 9})
        self.assertEqual(trace.input_timestamp, 123)
        self.assertEqual(trace.snapshot_status, "captured")

    def test_missing_snapshot_never_substitutes_previous_hub_state(self):
        trace = self.trace()
        trace.capture_input(IntersectionControlRequest(cross_id="100", current_time=1), None, has_datahub=True)
        self.assertIsNone(trace.traffic_snapshot)
        self.assertEqual(trace.snapshot_status, "unavailable")
        self.assertEqual(trace.input_request["cross_id"], "100")

    def test_nonfinite_opaque_cycles_and_mapping_keys_are_explicitly_marked(self):
        cyclic = []
        cyclic.append(cyclic)
        samples = [math.nan, object(), cyclic, {object(): 1}, {math.inf: 1}, {1: 1, "1": 2}, 10 ** 5000]
        for value in samples:
            with self.subTest(type=type(value).__name__):
                normalized = trace_value(value)
                encoded = json.dumps(normalized, allow_nan=False)
                self.assertIn("trace_omitted", encoded)

    def test_repeated_objects_are_not_mistaken_for_cycles(self):
        shared = {"flow": 5}
        request = IntersectionControlRequest(cross_id="100", current_time=1)
        self.assertEqual(trace_value([shared, shared]), [shared, shared])
        self.assertEqual(trace_value([request, request])[0], trace_value(request))

    def test_candidate_is_captured_independently_from_final_and_original_arrays(self):
        trace = self.trace()
        candidate = [20] + [0] * 8 + [1]
        trace.capture_plan(candidate)
        candidate[0] = 30
        trace.capture_plan(candidate, final=True)
        candidate[0] = 40
        self.assertEqual(trace.candidate_legacy[0], 20)
        self.assertEqual(trace.final_legacy[0], 30)
        self.assertEqual(trace.candidate_signal_plan.phase_times[0], 20)

    def test_invalid_candidate_is_preserved_as_diagnostics_without_fake_signal_plan(self):
        trace = self.trace()
        trace.capture_plan([math.nan])
        self.assertIsNone(trace.candidate_signal_plan)
        self.assertEqual(trace.candidate_legacy[0]["trace_omitted"], "non_finite_number")

    def test_emission_is_one_complete_standard_json_record_with_valid_utf8(self):
        trace = self.trace()
        trace.quality_issues = ["vendor\ud800\nmessage"]
        trace.status = "published"
        logger = Mock()
        trace.emit(logger)
        logger.info.assert_called_once()
        encoded = logger.info.call_args.args[1]
        encoded.encode("utf-8")
        record = json.loads(encoded)
        self.assertEqual(record["event"], "aitc.decision")
        self.assertEqual(record["status"], "published")
        self.assertGreaterEqual(record["latency_ms"], 0)
        self.assertNotIn("\n", encoded)

    def test_logging_sink_failure_is_explicit_and_does_not_fail_control(self):
        trace = self.trace()
        logger = Mock()
        logger.info.side_effect = OSError("disk full")
        with patch("runtime.tracing.sys.stderr", new_callable=io.StringIO) as stderr:
            trace.emit(logger)
        self.assertIn(trace.trace_id, stderr.getvalue())
        self.assertIn("OSError", stderr.getvalue())

    def test_stage_latency_uses_monotonic_clock_and_records_failed_stage(self):
        trace = self.trace()
        error = RuntimeError("coordination failed")
        with patch("runtime.tracing.perf_counter_ns", side_effect=[1_000_000, 4_000_000]):
            with self.assertRaises(RuntimeError) as raised:
                with trace_stage([trace], "coordination"):
                    raise error
        self.assertIs(raised.exception, error)
        self.assertEqual(trace.stage_latency_ms["coordination"], 3)
        self.assertEqual(trace.failed_stage, "coordination")


if __name__ == "__main__":
    unittest.main()
