"""DataHub composition, control-boundary capture and frozen legacy replay."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import Lambdas
from pydantic import ValidationError

from app.config import RuntimeSettings, TrafficMemorySettings
from app.core.control.policies import BaselineController
from infra.data import ResultWarehouse, ShortTermMemory, TrafficDataHub
from runtime import PeriodicDecisionPipeline
from runtime.application import create_application
from test.fixtures.v2_baseline_controller import (
    FIXED_TIME, FIXTURE, compact_round, config_sources, full_replay, sensor_request,
)
from test.test_decision_pipeline import _Lambdas, _LegacyProcessor, _Predictor, _Writer
from test.test_traffic_datahub import deep_json


class DataHubIntegrationTest(unittest.TestCase):
    def _make_pipeline(self, selector, *, memory_window=2):
        cache = ShortTermMemory()
        hub = TrafficDataHub(cache=cache, lambdas_module=_Lambdas, memory_window=memory_window)
        pipeline = PeriodicDecisionPipeline(
            cache=cache, data_processor=_LegacyProcessor(), lambdas_module=_Lambdas,
            writer=_Writer(), result_warehouse=ResultWarehouse(),
            flow_predictor=_Predictor(), queue_predictor=_Predictor(),
            dqn_select=selector, coordinate=lambda action, *_args: action,
            phase_check=lambda action: (action, {}),
            select_data_to_send=lambda intersection_id, action, traffic, model: {
                "id": intersection_id, "action": action, "traffic": traffic, "model": model,
            },
            is_millisecond_timestamp=lambda _value: True,
            overflow_warning_map={"100": {}}, radar_event_map={}, flow_duration_seconds=150,
            datahub=hub,
        )
        return pipeline, hub

    def test_prefixed_environment_configuration_takes_precedence(self):
        with patch.dict(os.environ, {
            "AITC_MEMORY_WINDOW": "2", "MEMORY_WINDOW": "7", "AITC_DATAHUB_EVENT_LIMIT": "4",
        }, clear=True), patch("app.config._load_dotenv"):
            settings = RuntimeSettings.from_environment()
        self.assertEqual(settings.traffic_memory.memory_window, 2)
        self.assertEqual(settings.traffic_memory.datahub_event_limit, 4)

    def test_unprefixed_memory_window_alias_is_supported(self):
        with patch.dict(os.environ, {"MEMORY_WINDOW": "3"}, clear=True):
            settings = TrafficMemorySettings()
        self.assertEqual(settings.memory_window, 3)

    def test_explicit_settings_fields_override_the_environment(self):
        with patch.dict(os.environ, {"AITC_MEMORY_WINDOW": "7"}, clear=True):
            settings = TrafficMemorySettings(memory_window=2, datahub_event_limit=4)
        self.assertEqual(settings.memory_window, 2)
        self.assertEqual(settings.datahub_event_limit, 4)

    def test_invalid_memory_configuration_fails_before_application_assembly(self):
        for name in ("AITC_MEMORY_WINDOW", "MEMORY_WINDOW", "AITC_DATAHUB_EVENT_LIMIT"):
            for value in ("0", "-1", "invalid", "1.5", "2.0", "true"):
                with self.subTest(name=name, value=value), patch.dict(
                    os.environ, {name: value}, clear=True,
                ), patch("app.config._load_dotenv"):
                    with self.assertRaises(ValidationError):
                        RuntimeSettings.from_environment()

    def test_explicit_memory_configuration_rejects_booleans_and_float_values(self):
        for field in ("memory_window", "datahub_event_limit"):
            for value in (True, 2.0, "2.0"):
                with self.subTest(field=field, value=value), patch.dict(os.environ, {}, clear=True):
                    with self.assertRaises(ValidationError):
                        TrafficMemorySettings(**{field: value})

    def test_application_shares_one_hub_for_protocols_processing_query_and_control(self):
        with tempfile.TemporaryDirectory(prefix="aitc-datahub-") as directory:
            root = Path(directory)
            settings = RuntimeSettings(
                runtime_data_dir=root / "history", runtime_output_dir=root / "output",
                prediction_data_dir=root / "prediction", control_snapshot_dir=root / "snapshot",
                enable_config_sync=False, enable_prediction_scheduler=False,
                enable_experience_pool_scheduler=False,
                traffic_memory=TrafficMemorySettings(memory_window=2, datahub_event_limit=4),
            )
            with patch("runtime.application.OpenAICompatibleLLMClient.list_models") as models:
                app = create_application(settings=settings)
                try:
                    hub = app.datahub
                    receiver = app.http_server.ingestor.receiver
                    self.assertIs(app.tcp_server.ingestor.receiver, receiver)
                    self.assertIs(receiver.datahub, hub)
                    self.assertIs(app.decision_pipeline.datahub, hub)
                    self.assertIs(app.decision_pipeline.data_processor.datahub, hub)
                    self.assertIs(app.http_server.query_service.datahub, hub)
                    self.assertIs(receiver.cache, hub.cache)
                    self.assertIs(app.decision_pipeline.cache, hub.cache)
                    self.assertIs(app.http_server.query_service._short_term_memory, hub.cache)
                    self.assertIsNone(app.http_server._server)
                    self.assertIsNone(app.tcp_server._server_socket)
                    models.assert_not_called()

                    cross_id = Lambdas.intersection_list[0]
                    stage = {"CrossId": cross_id, "time": FIXED_TIME * 1000,
                             "curStageNo": "1", "curStageLen": 0}
                    with patch("time.time", return_value=FIXED_TIME):
                        app.tcp_server.ingestor.ingest_tcp_item(stage)
                        self.assertEqual(hub.query(cross_id, "video").events[0].payload, stage)
                        self.assertEqual(app.decision_pipeline.data_processor.snapshot()["stage"], [stage])
                finally:
                    app.stop()

    def test_configured_history_capacity_is_used_by_the_composed_hub(self):
        with tempfile.TemporaryDirectory(prefix="aitc-datahub-") as directory, patch.dict(
            os.environ, {"AITC_MEMORY_WINDOW": "2"}, clear=True,
        ), patch("app.config._load_dotenv"):
            settings = RuntimeSettings.from_environment()
            # Use isolated paths while preserving the loaded nested settings.
            root = Path(directory)
            settings = RuntimeSettings(
                runtime_data_dir=root / "history", runtime_output_dir=root / "output",
                prediction_data_dir=root / "prediction", enable_prediction_scheduler=False,
                enable_experience_pool_scheduler=False, traffic_memory=settings.traffic_memory,
            )
            app = create_application(settings=settings)
            try:
                for index in range(4):
                    app.datahub.capture(sensor_request("1300068", FIXED_TIME + index))
                app.datahub.capture(sensor_request("1300103", FIXED_TIME))
                self.assertEqual([snapshot.current_time for snapshot in app.datahub.history("1300068")],
                                 [FIXED_TIME + 2, FIXED_TIME + 3])
                self.assertEqual(app.datahub.latest("1300068").current_time, FIXED_TIME + 3)
                self.assertEqual(len(app.datahub.history("1300103")), 1)
            finally:
                app.stop()

    def test_pipeline_captures_before_selector_mutation_and_preserves_copied_state(self):
        seen = []
        hub = None

        def selector(request):
            captured = hub.latest(request.cross_id)
            self.assertIsNotNone(captured)
            self.assertEqual(captured.traffic_vector, request.traffic_vector)
            self.assertEqual(captured.previous_coordinate, request.previous_coordinate)
            seen.append(copy.deepcopy(request))
            request.traffic_vector[0] = 999
            request.previous_coordinate["100"]["phase"][0] = 999
            return [10] + [0] * 8 + [1], {}, [], {}

        pipeline, hub = self._make_pipeline(selector)
        pipeline.last_coordinate_set = {"100": {"phase": [3]}}
        with patch("time.time", return_value=FIXED_TIME):
            pipeline.run_once()
        self.assertEqual(len(seen), 1)
        captured = hub.latest("100")
        self.assertEqual(captured.traffic_vector, seen[0].traffic_vector)
        self.assertEqual(captured.previous_coordinate, {"100": {"phase": [3]}})
        self.assertEqual(captured.current_time, FIXED_TIME)

    def test_strict_snapshot_failure_does_not_block_the_legacy_selector(self):
        selector = Mock(return_value=([25] + [0] * 8 + [1], {}, [], {}))
        pipeline, hub = self._make_pipeline(selector)
        with patch("time.time", return_value=-1):
            result = pipeline.run_once()
        selector.assert_called_once()
        self.assertEqual(selector.call_args.args[0].current_time, -1)
        self.assertEqual(result[0]["action"][0], 25)
        self.assertIsNone(hub.latest("100"))
        view = hub.query("100")
        self.assertIn("snapshot_current_round", view.missing_fields)
        self.assertTrue(any("snapshot_validation_failed" in issue for issue in view.quality_issues))

    def test_deep_snapshot_copy_failure_keeps_the_legacy_control_path_running(self):
        selector = Mock(return_value=([25] + [0] * 8 + [1], {}, [], {}))
        pipeline, hub = self._make_pipeline(selector)
        prediction = {"vendor": deep_json()}
        pipeline.flow_predictor.get_current_flow_prediction = lambda: prediction
        result = pipeline.run_once()
        selector.assert_called_once()
        self.assertIs(selector.call_args.args[0].predicted_flow, prediction)
        self.assertEqual(result[0]["action"][0], 25)
        self.assertIsNone(hub.latest("100"))
        self.assertTrue(any("snapshot_capture_failed" in issue for issue in hub.query("100").quality_issues))

    def test_enabled_hub_preserves_two_rounds_of_real_control_and_tcp_golden_output(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(config_sources(), golden["config_sources"])
        hub = TrafficDataHub(lambdas_module=Lambdas, memory_window=2)
        controller = BaselineController()

        def selector(request):
            self.assertIsNotNone(hub.capture(request))
            return controller.select_legacy(request)

        actual = full_replay(selector, controller.coordinate_legacy)
        self.assertEqual(actual, full_replay())
        self.assertEqual(len(actual), 2)
        for index, result in enumerate(actual):
            with self.subTest(round=index):
                self.assertEqual(compact_round(result), golden["rounds"][index])
                self.assertEqual(len(result["after_phase_check"]), 186)
                self.assertEqual(len(result["tcp_frames"]), 186)
        for cross_id in Lambdas.intersection_list:
            with self.subTest(intersection=cross_id):
                history = hub.history(cross_id)
                self.assertEqual(len(history), 2)
                self.assertEqual([snapshot.current_time for snapshot in history],
                                 [FIXED_TIME, FIXED_TIME + 120])
                expected = sensor_request(cross_id, observed=cross_id in {"1300068", "1300103"})
                self.assertEqual(history[0].traffic_vector, expected.traffic_vector)
                self.assertEqual(history[1].traffic_vector, expected.traffic_vector)
                self.assertEqual(hub.latest(cross_id), history[-1])


if __name__ == "__main__":
    unittest.main()
