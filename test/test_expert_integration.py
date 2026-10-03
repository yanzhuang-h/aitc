"""Real composition and legacy replay with source-only, read-only experts."""

import copy
import json
import random
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import Lambdas
from pydantic import ValidationError

from agent.experts import EVExpert, InternetExpert, RadarExpert, VideoExpert
from app.config import RuntimeSettings, TrafficMemorySettings
from app.core.control.policies import BaselineController
from infra.data import RuntimeDataProcessor, TrafficDataHub
from infra.data.classifier import DataKind, DataSource
from infra.data.traffic_schemas import ExpertTrafficState, RawTrafficEvent, TrafficSnapshot
from runtime.application import create_application
from test.fixtures.v2_baseline_controller import (
    FIXED_TIME, FIXTURE, compact_round, full_replay, isolated_runtime, sensor_request,
)


VIDEO_INTERSECTION = "1300068"
RADAR_INTERSECTION = "1300271"
RADAR_DEVICE = "radar-ximenzi-333-01"


def source_payloads(now):
    """Actual wire formats, using the configured detector and radar device IDs."""
    return (
        (DataKind.FLOW, DataSource.TCP, {
            "ycsb_xsfx": "L", "jtll_ddbh": "1", "ycsb_cdbh": "0", "ts": now * 1000,
        }),
        (DataKind.QUEUE, DataSource.TCP, {
            "jtll_ddbh": "1", "start_time": now * 1000,
            "car_nums": [{"ycsb_cdbh": "0", "queue": 12, "all": 18}],
        }),
        (DataKind.RADAR, DataSource.HTTP, {"deviceNo": RADAR_DEVICE, "speed": 32}),
    )


def ingest_observations(hub, now):
    for kind, source, payload in source_payloads(now):
        hub.ingest(RawTrafficEvent(
            kind=kind, source=source, received_at=now, payload=payload,
        ))


@contextmanager
def composed_application():
    with tempfile.TemporaryDirectory(prefix="aitc-experts-") as directory:
        root = Path(directory)
        settings = RuntimeSettings(
            runtime_data_dir=root / "history", runtime_output_dir=root / "output",
            prediction_data_dir=root / "prediction", control_snapshot_dir=root / "snapshot",
            enable_config_sync=False, enable_prediction_scheduler=False,
            enable_experience_pool_scheduler=False,
            traffic_memory=TrafficMemorySettings(memory_window=2, datahub_event_limit=32),
        )
        app = create_application(settings=settings)
        try:
            yield app
        finally:
            app.stop()


class ExpertIntegrationTest(unittest.TestCase):
    def test_composed_experts_read_shared_protocol_observations_without_llm_or_plan(self):
        with patch("time.time", return_value=FIXED_TIME), patch(
            "runtime.application.OpenAICompatibleLLMClient._open_json",
            side_effect=AssertionError("expert extraction must not request an LLM"),
        ) as llm, composed_application() as app:
            self.assertEqual(set(app.experts), {"video", "radar", "internet", "ev"})
            for expert in app.experts.values():
                self.assertIs(expert.datahub, app.datahub)
            for _kind, source, payload in source_payloads(FIXED_TIME):
                if source == DataSource.TCP:
                    app.tcp_server.ingestor.ingest_tcp_item(payload)
                else:
                    app.http_server.ingestor.receiver.receive_http(payload)
            video = app.experts["video"].extract(VIDEO_INTERSECTION)
            radar = app.experts["radar"].extract(RADAR_INTERSECTION)
            self.assertEqual(video.observation.traffic_vector, [1, 0, 0, 0])
            self.assertEqual(video.observation.queue_vector["L"][0], 12)
            self.assertEqual(radar.observation.radar_map[FIXED_TIME][0]["speed"], 32)
            self.assertIsNone(app.datahub.latest(VIDEO_INTERSECTION))
            for state in (video, radar):
                self.assertIsInstance(state, ExpertTrafficState)
                self.assertEqual(set(state.model_dump()), {
                    "source", "observation", "missing_fields", "confidence",
                })
                self.assertFalse(hasattr(state.observation, "phase_times"))
            for source in ("internet", "ev"):
                with self.assertRaises(NotImplementedError):
                    app.experts[source].extract(VIDEO_INTERSECTION)
            self.assertIsNone(app.http_server._server)
            self.assertIsNone(app.tcp_server._server_socket)
            llm.assert_not_called()

    def test_actual_legacy_pipeline_is_unchanged_when_every_expert_would_fail(self):
        def run_round(expert_patches):
            with isolated_runtime(), ExitStack() as stack:
                calls = [stack.enter_context(patch.object(
                    cls, "extract", side_effect=AssertionError("Phase 4 experts are not pipeline nodes"),
                )) for cls in expert_patches]
                llm = stack.enter_context(patch(
                    "runtime.application.OpenAICompatibleLLMClient._open_json",
                    side_effect=AssertionError("legacy control must not request an LLM"),
                ))
                with composed_application() as app:
                    # Serial selection keeps real legacy random diagnostics reproducible.
                    app.decision_pipeline.worker_count = 1
                    with patch.object(
                        app.decision_pipeline, "dqn_select", wraps=app.decision_pipeline.dqn_select,
                    ) as selector:
                        payloads = app.decision_pipeline.run_once()
                    self.assertEqual(selector.call_count, 186)
                    self.assertEqual(len(payloads), 186)
                    self.assertEqual(payloads, app.decision_pipeline.result_warehouse.snapshot())
                    # Empty prediction storage preserves legacy None values. The
                    # strict sidecar reports those values without blocking control.
                    self.assertIn("snapshot_current_round", app.datahub.query(
                        VIDEO_INTERSECTION,
                    ).missing_fields)
                    llm.assert_not_called()
                    for call in calls:
                        call.assert_not_called()
                    return payloads

        expected = run_round(())
        actual = run_round((VideoExpert, RadarExpert, InternetExpert, EVExpert))
        self.assertEqual(actual, expected)

    def test_read_only_expert_extraction_preserves_two_round_control_and_tcp_golden(self):
        golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
        hub = TrafficDataHub(lambdas_module=Lambdas, memory_window=2)
        controller = BaselineController()
        video, radar = VideoExpert(hub), RadarExpert(hub)
        round_times = set()
        observed_sources = set()
        template_names = (
            "map_lambda", "intersection_flow_lambda", "max_lengths_lambda",
            "flow_map_single_intersection_lambda", "queue_map_single_intersection_lambda",
            "eventMap_Overflow_lambda",
        )

        def selector(request):
            if request.current_time not in round_times:
                ingest_observations(hub, request.current_time)
                round_times.add(request.current_time)
            self.assertIsNotNone(hub.capture(request))
            before_request = copy.deepcopy(request)
            before_cache = copy.deepcopy({
                kind: hub.cache.recent_legacy_tuples(kind)
                for kind in (DataKind.FLOW, DataKind.QUEUE, DataKind.RADAR)
            })
            before_templates = {name: copy.deepcopy(getattr(Lambdas, name))
                                for name in template_names}
            before_random = random.getstate()
            for expert in (video, radar):
                state = expert.extract(request.cross_id)
                self.assertEqual(state.observation.cross_id, request.cross_id)
                if state.confidence > 0:
                    observed_sources.add(state.source)
            self.assertEqual(request, before_request)
            self.assertEqual(random.getstate(), before_random)
            for kind, expected in before_cache.items():
                self.assertEqual(hub.cache.recent_legacy_tuples(kind), expected)
            for name, expected in before_templates.items():
                self.assertEqual(getattr(Lambdas, name), expected, name)
            return controller.select_legacy(request)

        actual = full_replay(selector, controller.coordinate_legacy)
        self.assertEqual(actual, full_replay())
        self.assertEqual(observed_sources, {"video", "radar"})
        self.assertEqual(round_times, {FIXED_TIME, FIXED_TIME + 120})
        for index, result in enumerate(actual):
            with self.subTest(round=index):
                self.assertEqual(compact_round(result), golden["rounds"][index])
                self.assertEqual(len(result["tcp_frames"]), 186)
                self.assertTrue(all(frame.endswith(b"\n") for frame in result["tcp_frames"]))
        for intersection_id in Lambdas.intersection_list:
            self.assertEqual(len(hub.history(intersection_id)), 2)

    def test_event_only_query_keeps_events_without_copying_captured_snapshot(self):
        with patch("time.time", return_value=FIXED_TIME):
            hub = TrafficDataHub(lambdas_module=Lambdas)
            ingest_observations(hub, FIXED_TIME)
            hub.capture(sensor_request(VIDEO_INTERSECTION, observed=True))
            original_deepcopy = copy.deepcopy
            with patch("infra.data.datahub.copy.deepcopy", wraps=original_deepcopy) as copies:
                events = hub.query(VIDEO_INTERSECTION, source="video", include_snapshot=False)
                self.assertFalse(any(
                    isinstance(call.args[0], TrafficSnapshot) for call in copies.call_args_list
                ))
            full = hub.query(VIDEO_INTERSECTION, source="video")
            self.assertIsNone(events.snapshot)
            self.assertNotIn("snapshot", events.missing_fields)
            self.assertIsNotNone(full.snapshot)
            self.assertEqual(events.events, full.events)
            events.events[0].payload["jtll_ddbh"] = "changed"
            self.assertEqual(hub.query(VIDEO_INTERSECTION, source="video").events[0].payload["jtll_ddbh"], "1")

    def test_event_only_query_rejects_non_boolean_flags(self):
        hub = TrafficDataHub(lambdas_module=Lambdas)
        for flag in (0, 1, "false", None, [], {}):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                hub.query(VIDEO_INTERSECTION, include_snapshot=flag)

    def test_experts_revalidate_foreign_views_and_reject_wrong_source_or_intersection(self):
        with patch("time.time", return_value=FIXED_TIME):
            hub = TrafficDataHub(lambdas_module=Lambdas)
            ingest_observations(hub, FIXED_TIME)
            good = hub.query(VIDEO_INTERSECTION, source="video", include_snapshot=False)
            bad_event = good.events[0].model_copy(update={"intersection_id": RADAR_INTERSECTION})
            cases = (
                ({"source": "unrecognized"}, ValidationError),
                ({"source": "radar"}, ValueError),
                ({"intersection_id": RADAR_INTERSECTION}, ValueError),
                ({"events": [bad_event]}, ValueError),
            )
            for fields, error in cases:
                with self.subTest(fields=fields), patch.object(
                    hub, "query", return_value=good.model_copy(update=fields),
                ), self.assertRaises(error):
                    VideoExpert(hub).extract(VIDEO_INTERSECTION)

    def test_explicit_envelope_partition_does_not_forge_a_sensor_mapping(self):
        with patch("time.time", return_value=FIXED_TIME):
            hub = TrafficDataHub(lambdas_module=Lambdas)
            hub.ingest(RawTrafficEvent(
                kind=DataKind.FLOW, source=DataSource.TCP, received_at=FIXED_TIME,
                intersection_id=VIDEO_INTERSECTION,
                payload={"ycsb_xsfx": "L", "jtll_ddbh": "5", "ycsb_cdbh": "0", "ts": FIXED_TIME * 1000},
            ))
            hub.ingest(RawTrafficEvent(
                kind=DataKind.RADAR, source=DataSource.HTTP, received_at=FIXED_TIME,
                intersection_id=VIDEO_INTERSECTION, payload={"deviceNo": RADAR_DEVICE, "speed": 32},
            ))
            video = VideoExpert(hub).extract(VIDEO_INTERSECTION)
            radar = RadarExpert(hub).extract(VIDEO_INTERSECTION)
            self.assertEqual(video.observation.traffic_vector, [])
            self.assertEqual(video.confidence, 0)
            self.assertEqual(radar.observation.radar_map, {})
            self.assertEqual(radar.confidence, 0)

    def test_radar_extraction_does_not_advance_legacy_overflow_template_mutation(self):
        with patch("time.time", return_value=FIXED_TIME):
            hub = TrafficDataHub(
                lambdas_module=Lambdas,
                overflow_warning_map=copy.deepcopy(Lambdas.map_lambda),
                radar_event_map={key: {} for key in Lambdas.radar_event_list},
            )
            hub.ingest(RawTrafficEvent(
                kind=DataKind.RADAR_EVENT, source=DataSource.HTTP,
                received_at=FIXED_TIME,
                payload={"deviceNo": RADAR_DEVICE, "eventType": "OverFlow", "createTime": ""},
            ))
            processor = RuntimeDataProcessor(hub.cache, Lambdas, datahub=hub)
            initial = copy.deepcopy(Lambdas.eventMap_Overflow_lambda)
            before_events = copy.deepcopy(hub.radar_event_map)
            with patch.object(Lambdas, "eventMap_Overflow_lambda", copy.deepcopy(initial)):
                expected = processor.radar_event(hub.radar_event_map, hub.overflow_warning_map)
                expected_template = copy.deepcopy(Lambdas.eventMap_Overflow_lambda)
            with patch.object(Lambdas, "eventMap_Overflow_lambda", copy.deepcopy(initial)):
                radar = RadarExpert(hub).extract(RADAR_INTERSECTION)
                self.assertEqual(radar.observation.overflow_map, {})
                self.assertIn("overflow_map", radar.missing_fields)
                self.assertEqual(Lambdas.eventMap_Overflow_lambda, initial)
                self.assertEqual(hub.radar_event_map, before_events)
                actual = processor.radar_event(hub.radar_event_map, hub.overflow_warning_map)
                self.assertEqual(actual, expected)
                self.assertEqual(Lambdas.eventMap_Overflow_lambda, expected_template)


if __name__ == "__main__":
    unittest.main()
