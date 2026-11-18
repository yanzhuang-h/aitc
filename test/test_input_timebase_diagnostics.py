"""生产时间诊断只读，摘要与业务输入、最终报文互不污染。"""

import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from datahub.classifier import DataKind
from datahub.memory.short_term import ShortTermMemory
from datahub.runtime_processor import RuntimeDataProcessor
from runtime.input_diagnostics import summarize_input_timebases
from test.fixtures.v2_acceptance import acceptance_application
from test.fixtures.v2_baseline_controller import FIXED_TIME, isolated_runtime
from test.test_production_diagnostics import emitted


ROAD = "1700125"
STAMP = 1_790_000_000


class InputTimebaseDiagnosticsTests(unittest.TestCase):
    def summarize(self, flow=(), extend=()):
        return summarize_input_timebases(flow, extend, {1: (ROAD, "U"), 2: ("1300069", "L")})

    def test_milliseconds_seconds_and_source_order_have_explicit_statistics(self):
        flow = [(STAMP + 2, {"jtll_ddbh": "1", "ts": STAMP * 1000, "plate": "not-for-diagnostics"}),
                (STAMP + 3, {"jtll_ddbh": 1, "ts": STAMP}),
                (STAMP + 4, {"jtll_ddbh": 1, "ts": (STAMP - 1) * 1000})]
        original = copy.deepcopy(flow)
        result = self.summarize(flow)
        row = result["flow"]["by_road"][ROAD]
        self.assertEqual(row["cache_span_seconds"], 2)
        self.assertEqual(row["payload_span_seconds"], 1)
        self.assertEqual(row["cache_unique_seconds"], 3)
        self.assertEqual(row["payload_unique_seconds"], 2)
        self.assertEqual(row["payload_time_repeated_records"], 1)
        self.assertEqual(row["payload_time_backwards_records"], 1)
        self.assertEqual(row["cache_minus_payload_mean_seconds"], 3.333)
        self.assertEqual(row["detector_records"], {"1": 3})
        self.assertEqual(flow, original)
        self.assertNotIn("plate", json.dumps(result))
        self.assertNotIn("not-for-diagnostics", json.dumps(result))
        self.assertEqual(result["cache_timestamp_semantics"], "cache_insertion_after_persistence")

    def test_missing_malformed_future_and_invalid_stage_times_remain_observable(self):
        extend = [(STAMP, {"CrossId": ROAD, "curStageNo": "0"}),
                  (STAMP + 1, {"CrossId": ROAD, "curStageNo": "bad", "time": "invalid"}),
                  (STAMP + 2, {"CrossId": ROAD, "curStageNo": "1", "time": True}),
                  (STAMP + 3, {"CrossId": ROAD, "curStageNo": "1", "time": 10**400}),
                  (float("nan"), {"CrossId": ROAD, "curStageNo": "1", "time": STAMP * 1000}),
                  (STAMP + 4, {"CrossId": ROAD, "curStageNo": "0", "time": (STAMP + 10) * 1000})]
        result = self.summarize(extend=extend)
        row = result["extend"]["by_road"][ROAD]
        self.assertEqual(row["records"], 6)
        self.assertEqual(row["missing_payload_time_records"], 1)
        self.assertEqual(row["invalid_payload_time_records"], 3)
        self.assertEqual(row["invalid_cache_time_records"], 1)
        self.assertEqual(row["cache_minus_payload_min_seconds"], -6)
        json.dumps(result, allow_nan=False)

    def test_unmapped_detector_and_historical_scope_are_distinct(self):
        result = self.summarize([
            (STAMP, {"jtll_ddbh": "99", "ts": STAMP * 1000}),
            (STAMP, {"jtll_ddbh": "invalid", "ts": STAMP * 1000}),
            (STAMP, {"jtll_ddbh": "2", "ts": STAMP * 1000}),
        ])
        self.assertEqual(result["flow"]["unmapped_identifiers"], {"99": 1, "<invalid>": 1})
        self.assertEqual(result["flow"]["outside_scope_records"], 1)
        self.assertEqual(result["flow"]["by_road"], {})

    def test_unavailable_timestamps_are_not_reported_as_an_empty_observed_cache(self):
        result = self.summarize(None, [])
        self.assertFalse(result["flow"]["cache_timestamps_available"])
        self.assertTrue(result["extend"]["cache_timestamps_available"])

    def test_cache_timestamp_unit_is_not_silently_changed(self):
        result = self.summarize([(STAMP * 1000, {"jtll_ddbh": "1", "ts": STAMP * 1000})])
        row = result["flow"]["by_road"][ROAD]
        self.assertEqual(row["cache_timestamp_first"], STAMP * 1000)
        self.assertEqual(row["payload_timestamp_first"], STAMP)

    def test_snapshot_business_payloads_and_diagnostic_tuples_share_one_read(self):
        cache = ShortTermMemory()
        payload = {"jtll_ddbh": 1, "ts": STAMP * 1000}
        cache.add(DataKind.FLOW, payload, timestamp=STAMP)
        processor = RuntimeDataProcessor(cache, SimpleNamespace())
        with patch("time.time", return_value=STAMP + 1):
            snapshot = processor.snapshot()
        self.assertEqual(snapshot["flow_received"], [(STAMP, payload)])
        self.assertEqual(snapshot["flow"], [payload])
        self.assertIs(snapshot["flow"][0], snapshot["flow_received"][0][1])
        self.assertEqual(payload, {"jtll_ddbh": 1, "ts": STAMP * 1000})

    def test_real_pipeline_emits_one_batch_summary_without_changing_selector_or_wire(self):
        with isolated_runtime(), acceptance_application() as (app, logger):
            detector = next(detector for detector, location in app.datahub.lambdas.location_to_intersection_lambda.items()
                            if str(location[0]) == ROAD)
            app.datahub.cache.add(DataKind.FLOW, {
                "jtll_ddbh": str(detector), "ts": (FIXED_TIME - 3.5) * 1000,
                "ycsb_cdbh": "1", "ycsb_xsfx": "1B",
            }, timestamp=FIXED_TIME - 1.2)
            app.datahub.cache.add(DataKind.EXTEND, {
                "CrossId": ROAD, "curStageNo": "1", "time": (FIXED_TIME - 4) * 1000,
            }, timestamp=FIXED_TIME - 0.5)
            with patch.object(app.decision_pipeline, "dqn_select",
                              wraps=app.decision_pipeline.dqn_select) as select:
                result = app.decision_pipeline.run_once()
            batch, = [item for item in emitted(logger) if item["event"] == "aitc.decision_batch"]
            self.assertEqual(select.call_count, 235)
            self.assertEqual(len(result), 235)
            self.assertNotIn("input_timebase", json.dumps(result))
            self.assertEqual(result, app.decision_pipeline.result_warehouse.snapshot())
            summary = batch["input_timebase"]
            self.assertEqual(summary["flow"]["by_road"][ROAD]["records"], 1)
            self.assertEqual(summary["flow"]["by_road"][ROAD]["cache_minus_payload_mean_seconds"], 2.3)
            self.assertEqual(summary["extend"]["by_road"][ROAD]["cache_minus_payload_mean_seconds"], 3.5)


if __name__ == "__main__":
    unittest.main()
