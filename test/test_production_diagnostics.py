"""诊断日志贯通输入、配置、格式化方案与发送副本，保持控制和协议不变。"""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stderr
import io
import json
import logging
import logging.handlers
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from Server_AITC import setup_logging
from datahub.output_store import FileRuntimeOutputStore
from datahub.result_sender import ResultSender
from datahub.writer import RuntimeDataWriter
from infra.logging import decision_batch_id, plan_fingerprint
from lib.control_functions.global_processors.finalization import finalize_plan_values
from lib.data_ANS.flow_allocator_shadow import record_shadow_comparison
from runtime.tracing import DecisionTrace, emit_batch_input
from test import test_decision_pipeline as fixtures
from test import test_result_sender as socket_fixtures


def emitted(logger):
    return [json.loads(call.args[1]) for call in logger.info.call_args_list
            if call.args[0] == "%s"]


class ProductionDiagnosticsTests(unittest.TestCase):
    def test_server_keeps_full_decision_events_in_file_only(self):
        logger = logging.Logger("server-test")
        console = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.log"
            handler = logging.handlers.TimedRotatingFileHandler(path, encoding="utf-8")
            with (
                closing(handler),
                patch("Server_AITC.logging.getLogger", return_value=logger),
                patch("Server_AITC.logging.handlers.TimedRotatingFileHandler", return_value=handler),
                redirect_stderr(console),
            ):
                setup_logging()
                emit_batch_input(logger, "batch", input_timebase={"flow": {"records": 14}})
                DecisionTrace(batch_id="batch", intersection_id="1700125", control_policy="test").emit(logger)
                logger.warning("runtime warning")
            saved = path.read_text(encoding="utf-8")
        self.assertIn('"event":"aitc.decision_batch"', saved)
        self.assertIn('"event":"aitc.decision"', saved)
        self.assertIn('"records":14', saved)
        self.assertIn("runtime warning", saved)
        self.assertNotIn('"event":"aitc.decision', console.getvalue())
        self.assertIn("runtime warning", console.getvalue())

    def test_batch_context_reaches_workers_and_is_isolated_between_runs(self):
        def run(_):
            observed = []
            def select(request):
                observed.append(decision_batch_id.get())
                return ([30,30]+[0]*7+[1], {}, [], {})
            pipeline = fixtures.PeriodicDecisionPipelineTest()._make_pipeline(selector=select)
            pipeline.logger = Mock()
            pipeline.select_data_to_send = lambda road, action, *_: {
                "additional": {"tlLogic": {"id": road, "programID": action[9],
                                           "phase": [{"duration": action[0]}, {"duration": action[1]}]}}}
            results = pipeline.run_once()
            logs = emitted(pipeline.logger)
            batch, = [item for item in logs if item["event"] == "aitc.decision_batch"]
            record, = [item for item in logs if item["event"] == "aitc.decision"]
            self.assertEqual(record["input_context_batch_id"], batch["batch_id"])
            self.assertEqual(observed, [record["batch_id"]])
            self.assertEqual(record["formatted_plan"], results[0]["additional"]["tlLogic"])
            self.assertEqual(record["plan_sha256"], plan_fingerprint(record["formatted_plan"]))
            self.assertIsNone(decision_batch_id.get())
            return record["batch_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            batches = list(pool.map(run, range(2)))
        self.assertEqual(len(set(batches)), 2)
        self.assertIsNone(decision_batch_id.get())

    def test_failed_batch_restores_outer_context(self):
        pipeline = fixtures.PeriodicDecisionPipelineTest()._make_pipeline(
            coordinator=Mock(side_effect=RuntimeError("coordination failed")))
        token = decision_batch_id.set("outer")
        try:
            with self.assertRaises(RuntimeError):
                pipeline.run_once()
            self.assertEqual(decision_batch_id.get(), "outer")
        finally:
            decision_batch_id.reset(token)

    def test_shadow_keeps_real_lane_vectors_config_and_experience_profile(self):
        road = "1700125"
        cross = {road: {"phase": {"1": "U"}, "LaneNo": {"U": {"0": "1B"}},
                        "jtll_ddbh": {"42": "U"}, "Cycle": [[1]]}}
        table = {road: {"U": {"10": [100]+[0]*9, "20": [80]+[0]*9}}}
        flow = {1000: {"pass": {"U": [12]+[0]*6}}}
        extend = {t: [{"CrossId": road, "curStageNo": "1"}] for t in range(1000,1600)}
        originals = copy.deepcopy((cross, table, flow, extend))
        token = decision_batch_id.set("diagnostic-batch")
        try:
            with tempfile.TemporaryDirectory() as directory:
                record = record_shadow_comparison(
                    road, [30]*8+[0,0], flow, extend,
                    experience_table=table, cross_info=cross,
                    runtime_mode="new", log_directory=directory)
                saved = json.loads(Path(record["log_path"]).read_text())
        finally:
            decision_batch_id.reset(token)
        self.assertEqual(saved["batch_id"], "diagnostic-batch")
        self.assertEqual(saved["effective_cross_info"], cross[road])
        self.assertEqual(saved["runtime_input"]["observed_flow"]["U"], [12]+[0]*9)
        self.assertEqual(saved["runtime_input"]["observed_stage_seconds"], {"1":600})
        self.assertEqual(saved["runtime_input"]["flow_selection"]["selected_last_timestamp"],1000)
        self.assertEqual(saved["flow_10min_lane_vectors"]["U"], [12]+[0]*9)
        decision = saved["decisions"]["U"]
        self.assertEqual(decision["selected_green_time"], 10)
        self.assertEqual(decision["experience_profile"]["capacity_drop_count"], 1)
        self.assertEqual(decision["selected_capacity_lane_vector"], table[road]["U"]["10"])
        self.assertEqual(len(saved["experience_road_sha256"]), 64)
        self.assertEqual((cross, table, flow, extend), originals)

    def test_invalid_program_is_reported_without_diagnostic_code_raising(self):
        from lib.control_functions.global_processors.flow_control import process_flow_intersection
        result, report = process_flow_intersection(
            "1700125", [30,30,30,30]+[0]*6, {"0": None}, 12,
            lambda road, state: state, lambda road: {})
        self.assertFalse(report["success"])
        self.assertEqual(report["selected_program"], {})
        self.assertIn("error", report)
        self.assertEqual(len(result),10)

    def test_final_log_distinguishes_manual_offset_from_bound_clipping(self):
        road = "1700062"
        plan = [30,30]+[0]*7+[1]
        config = {"phase":["UD","LR"],"min_pass_time":[10,10],"max_pass_time":[40,100]}
        token = decision_batch_id.set("diagnostic-batch")
        try:
            with patch("lib.control_functions.global_processors.finalization.apply_floating_value",
                       return_value=({road:[50,30]+[0]*7+[1]},{})), \
                    self.assertLogs("FlowControl",level="INFO") as captured:
                actual,_ = finalize_plan_values({road:plan},road_info={road:{"1":config}})
        finally:
            decision_batch_id.reset(token)
        record = json.loads(captured.records[0].getMessage().split(" ",1)[1])
        self.assertEqual(record["batch_id"],"diagnostic-batch")
        self.assertEqual(record["before_floating"][:2],[30,30])
        self.assertEqual(record["after_floating_before_bounds"][:2],[50,30])
        self.assertEqual(record["bounded_phase_changes"],[{"index":0,"before":50,"after":40}])
        self.assertEqual(actual[road][:2],[40,30])
        self.assertEqual(record["selected_program"],config)

    def test_send_log_fingerprint_matches_formatted_plan_without_changing_wire(self):
        payload = {"additional":{"tlLogic":{"id":"1700062","programID":1,
                                            "phase":[{"duration":30},{"duration":40}]}}}
        original = copy.deepcopy(payload)
        with tempfile.TemporaryDirectory() as directory:
            writer = RuntimeDataWriter(FileRuntimeOutputStore(directory),
                                       experience_manifest_path=Path(directory)/"absent.json")
            sock = socket_fixtures._FakeSocket()
            ResultSender(writer=writer).send_batch([sock],[payload])
            record = json.loads(next(Path(directory,"send").glob("*.txt")).read_text())
        self.assertEqual(record["AITC_PLAN_SHA256"], plan_fingerprint(payload["additional"]["tlLogic"]))
        self.assertEqual(json.loads(sock.sent[0]), original)
        self.assertEqual(payload,original)
        self.assertNotIn("AITC_PLAN_SHA256",payload)

    def test_send_summary_distinguishes_no_client_and_disconnection(self):
        logger = Mock()
        sender = ResultSender(logger=logger)
        payload = {"cross_id":"1700062"}
        sender.send_batch([], [payload])
        self.assertEqual(logger.info.call_args.args[1:],(0,1,0,0))
        disconnected = sender.send_batch([socket_fixtures._FakeSocket(), socket_fixtures._BrokenSocket()],
                                        [payload,payload])
        self.assertEqual(len(disconnected),1)
        self.assertEqual(logger.info.call_args.args[1:],(2,2,2,1))

    def test_learning_schedule_exposes_source_delay_scope_and_threshold(self):
        from lib.data_ANS import experience_runtime as runtime
        logger = Mock()
        scheduler = runtime.ExperiencePoolScheduler(logger=logger)
        with patch("lib.data_ANS.experience_runtime.threading.Thread"), \
                patch.dict("os.environ", {"AITC_EXPERIENCE_POOL_MIN_SAMPLES":"30",
                                         "AITC_EXPERIENCE_POOL_INITIAL_DELAY_SECONDS":"0"}):
            scheduler.start()
        summary = json.loads(logger.info.call_args.args[1])
        self.assertEqual(summary["source_day_delay"], 1)
        self.assertEqual(summary["catchup_days"], 10)
        self.assertEqual(summary["minimum_samples"],"30")
        self.assertIn("1700125",summary["update_roads"])
        self.assertIn("1700062",summary["collection_roads"])

    def test_learning_run_logs_why_pool_did_not_change_table(self):
        from lib.data_ANS import experience_runtime as runtime
        logger = Mock()
        scheduler = runtime.ExperiencePoolScheduler(logger=logger)
        report = {"source_date":"2026-11-15","status":"completed_pool_updated_no_table_change",
                  "candidate_count":5,"minimum_sample_count":30,"table_updated":False,
                  "pool_summary":{"days":{"2026-11-15":{"status":"pool_updated_threshold_not_met",
                                                        "compression":{"summary":{"eligible_lane_cells":0}}}}}}
        with patch.object(runtime,"run_experience_pool_day",return_value=report):
            self.assertEqual(scheduler.run_for_date(source_date="2026-11-15"),report)
        summary = json.loads(logger.info.call_args.args[1])
        self.assertFalse(summary["table_updated"])
        self.assertEqual(summary["candidate_count"],5)
        self.assertEqual(summary["days"]["2026-11-15"]["eligible_lane_cells"],0)

    def test_startup_context_lists_runtime_paths_without_credentials(self):
        from test.test_model_gateway_integration import model_application
        with patch.dict("os.environ",{"NACOS_PASSWORD":"secret-not-to-log"}), \
                self.assertLogs("aitc.runtime",level="INFO") as captured:
            with model_application(enabled=False):
                pass
        encoded = captured.records[0].getMessage()
        context = json.loads(encoded.split(" ",1)[1])
        self.assertEqual(context["diagnostic_groups"],["19","49"])
        self.assertIn("online_experience_path",context)
        self.assertNotIn("secret-not-to-log",encoded)
        self.assertNotIn("NACOS_PASSWORD",encoded)


if __name__ == "__main__":
    unittest.main()
