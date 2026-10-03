"""专家从当前原始窗口提取真实观测，不生成方案或伪造缺失数据。"""

import copy
import unittest
from unittest.mock import patch

from pydantic import ValidationError

import Lambdas
from agent.experts import EVExpert, InternetExpert, RadarExpert, VideoExpert
from infra.data import cache_processor
from infra.data.classifier import DataKind, DataSource
from infra.data.datahub import TrafficDataHub
from infra.data.memory.short_term import ShortTermMemory
from infra.data.traffic_schemas import ExpertTrafficState, RawTrafficEvent
from lib.control_functions.types import IntersectionControlRequest


NOW = 1_700_000_000.0
VIDEO_INTERSECTION = "1300068"
RADAR_INTERSECTION = "1300271"
RADAR_DEVICE = "radar-ximenzi-333-01"
BOYAN_INTERSECTION = "1300644"
BOYAN_DEVICE = "000000000001"


def flow_payload(detector="1", lane="0", timestamp=None):
    return {
        "ycsb_xsfx": "L", "jtll_ddbh": detector, "ycsb_cdbh": lane,
        "ts": int(NOW * 1000) if timestamp is None else timestamp,
    }


def queue_payload(queue=12, all_nums=18, detector="1", lane="0"):
    return {
        "jtll_ddbh": detector, "start_time": int(NOW * 1000),
        "car_nums": [{"ycsb_cdbh": lane, "queue": queue, "all": all_nums}],
    }


class TrafficExpertTest(unittest.TestCase):
    def setUp(self):
        self.clock = patch("time.time", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.hub = TrafficDataHub(lambdas_module=Lambdas)

    def ingest(self, kind, payload, *, received_at=NOW, quality_issues=None,
               source=DataSource.TCP, hub=None):
        (hub or self.hub).ingest(RawTrafficEvent(
            kind=kind, source=source, received_at=received_at, payload=payload,
            quality_issues=[] if quality_issues is None else quality_issues,
        ))

    def ingest_video_pair(self, *, hub=None, quality_issues=None):
        self.ingest(DataKind.FLOW, flow_payload(), hub=hub,
                    quality_issues=quality_issues)
        self.ingest(DataKind.QUEUE, queue_payload(), hub=hub)

    def test_video_extracts_without_any_captured_control_snapshot(self):
        self.ingest_video_pair()
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertIsInstance(state, ExpertTrafficState)
        self.assertEqual(state.source, "video")
        self.assertEqual(state.observation.cross_id, VIDEO_INTERSECTION)
        self.assertEqual(state.observation.current_time, NOW)
        self.assertEqual(state.observation.traffic_vector, [1, 0, 0, 0])
        self.assertEqual(state.observation.queue_vector["L"][0], 12)
        self.assertEqual(state.confidence, 1)
        self.assertIsNone(self.hub.latest(VIDEO_INTERSECTION))

    def test_video_preserves_existing_aggregation_bucket_shapes(self):
        flow = flow_payload()
        queue = queue_payload()
        stage = {"CrossId": VIDEO_INTERSECTION, "time": int(NOW * 1000),
                 "curStageNo": "3", "curStageLen": "19"}
        extend = {"CrossId": VIDEO_INTERSECTION, "curStageRemainLen": 8}
        for kind, payload in ((DataKind.FLOW, flow), (DataKind.QUEUE, queue),
                              (DataKind.STAGE, stage), (DataKind.EXTEND, extend)):
            self.ingest(kind, payload)
        expected_flow, expected_flow_map = cache_processor.process_flow_data([flow], Lambdas)
        expected_queue, expected_queue_map = cache_processor.process_queue_data([queue], Lambdas)
        expected_stage = cache_processor.process_stage_data([stage], Lambdas)
        expected_extend = cache_processor.process_extend_data([(NOW, extend)], Lambdas)
        observation = VideoExpert(self.hub).extract(VIDEO_INTERSECTION).observation
        self.assertEqual(observation.traffic_vector, expected_flow[VIDEO_INTERSECTION])
        self.assertEqual(observation.flow_map, expected_flow_map[VIDEO_INTERSECTION])
        self.assertEqual(observation.queue_vector, expected_queue[VIDEO_INTERSECTION])
        self.assertEqual(observation.queue_map, expected_queue_map[VIDEO_INTERSECTION])
        self.assertEqual(observation.stage_map, expected_stage[VIDEO_INTERSECTION])
        self.assertEqual(observation.extend_map, expected_extend[VIDEO_INTERSECTION])

    def test_video_ignores_old_full_snapshot_and_other_source_fields(self):
        self.hub.capture(IntersectionControlRequest(
            cross_id=VIDEO_INTERSECTION, current_time=NOW - 600,
            traffic_vector=[999, 999, 999, 999], queue_vector={"L": [999]},
            predicted_flow={"old": 999}, predicted_queue={"old": 999},
            previous_coordinate={"old": 999}, radar_map={"old": 999},
            boyan_map={"old": 999}, overflow_map={"old": 999},
        ))
        self.ingest_video_pair()
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.traffic_vector, [1, 0, 0, 0])
        for field in ("previous_coordinate", "predicted_flow", "predicted_queue",
                      "radar_map", "boyan_map", "overflow_map"):
            with self.subTest(field=field):
                self.assertEqual(getattr(state.observation, field), {})
        self.assertEqual(self.hub.latest(VIDEO_INTERSECTION).traffic_vector[0], 999)

    def test_video_empty_window_does_not_return_template_zero_measurements(self):
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.traffic_vector, [])
        self.assertEqual(state.observation.traffic_vector_duration2, [])
        self.assertEqual(state.observation.queue_vector, [])
        for field in ("flow_map", "queue_map", "stage_map", "extend_map"):
            self.assertEqual(getattr(state.observation, field), {})
            self.assertIn(field, state.missing_fields)
        self.assertEqual(state.confidence, 0)

    def test_optional_video_fields_do_not_reduce_required_field_coverage(self):
        self.ingest_video_pair()
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertIn("stage_map", state.missing_fields)
        self.assertIn("extend_map", state.missing_fields)
        self.assertNotIn("flow_map", state.missing_fields)
        self.assertNotIn("queue_map", state.missing_fields)
        self.assertEqual(state.confidence, 1)

    def test_video_reports_partial_required_observation_coverage(self):
        self.ingest(DataKind.FLOW, flow_payload())
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.traffic_vector, [1, 0, 0, 0])
        self.assertEqual(state.observation.queue_vector, [])
        self.assertIn("queue_map", state.missing_fields)
        self.assertEqual(state.confidence, 0.5)

    def test_zero_queue_is_an_observed_value(self):
        self.ingest(DataKind.QUEUE, queue_payload(queue=0, all_nums=0))
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.queue_vector["L"][0], 0)
        self.assertTrue(state.observation.queue_map)
        self.assertNotIn("queue_map", state.missing_fields)
        self.assertEqual(state.confidence, 0.5)

    def test_empty_lane_list_does_not_count_as_a_queue_observation(self):
        payload = queue_payload()
        payload["car_nums"] = []
        self.ingest(DataKind.QUEUE, payload)
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.queue_map, {})
        self.assertEqual(state.observation.queue_vector, [])
        self.assertIn("queue_map", state.missing_fields)
        self.assertEqual(state.confidence, 0)

    def test_invalid_queue_numbers_do_not_become_zero_observations(self):
        for field in ("queue", "all"):
            for value in (float("nan"), float("inf"), -1, True):
                with self.subTest(field=field, value=value):
                    hub = TrafficDataHub(lambdas_module=Lambdas)
                    payload = queue_payload()
                    payload["car_nums"][0][field] = value
                    self.ingest(DataKind.QUEUE, payload, hub=hub)
                    state = VideoExpert(hub).extract(VIDEO_INTERSECTION)
                    self.assertEqual(state.observation.queue_map, {})
                    self.assertEqual(state.observation.queue_vector, [])
                    self.assertIn("queue_map", state.missing_fields)
                    self.assertEqual(state.confidence, 0)

    def test_replaced_infinite_queue_does_not_hide_an_invalid_window_maximum(self):
        self.ingest(DataKind.FLOW, flow_payload())
        self.ingest(DataKind.QUEUE, queue_payload(queue=float("inf")))
        self.ingest(DataKind.QUEUE, queue_payload(queue=12))
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.queue_map, {})
        self.assertEqual(state.observation.queue_vector, [])
        self.assertIn("queue_map", state.missing_fields)
        self.assertLessEqual(state.confidence, 0.5)
        self.assertTrue(state.observation.flow_map)

    def test_replaced_boolean_queue_does_not_hide_an_invalid_window_maximum(self):
        self.ingest(DataKind.FLOW, flow_payload())
        self.ingest(DataKind.QUEUE, queue_payload(queue=True))
        self.ingest(DataKind.QUEUE, queue_payload(queue=0))
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.queue_map, {})
        self.assertEqual(state.observation.queue_vector, [])
        self.assertIn("queue_map", state.missing_fields)
        self.assertLessEqual(state.confidence, 0.5)
        self.assertTrue(state.observation.flow_map)

    def test_large_finite_integer_queue_does_not_overflow_float_validation(self):
        huge_integer = 10 ** 400
        self.ingest(DataKind.FLOW, flow_payload())
        self.ingest(DataKind.QUEUE, queue_payload(queue=huge_integer))
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.queue_vector["L"][0], huge_integer)
        self.assertEqual(
            state.observation.queue_map[str(int(NOW))]["queue"]["L"][0],
            huge_integer,
        )
        self.assertNotIn("queue_map", state.missing_fields)
        self.assertEqual(state.confidence, 1)

    def test_invalid_flow_lane_types_are_missing_without_changing_legacy_data(self):
        for lane in (-1, True, 1.5):
            with self.subTest(lane=lane):
                hub = TrafficDataHub(lambdas_module=Lambdas)
                payload = flow_payload(lane=lane)
                self.ingest(DataKind.FLOW, payload, hub=hub)
                state = VideoExpert(hub).extract(VIDEO_INTERSECTION)
                self.assertEqual(state.observation.flow_map, {})
                self.assertEqual(state.observation.traffic_vector, [])
                self.assertEqual(state.observation.traffic_vector_duration2, [])
                self.assertIn("flow.ycsb_cdbh", state.missing_fields)
                cached = hub.cache.recent_data(DataKind.FLOW)
                self.assertEqual(cached, [payload])
                self.assertIs(type(cached[0]["ycsb_cdbh"]), type(lane))
                legacy_vector, _legacy_map = cache_processor.process_flow_data(cached, Lambdas)
                self.assertEqual(legacy_vector[VIDEO_INTERSECTION], [1, 0, 0, 0])

    def test_invalid_queue_lane_types_are_missing_without_changing_legacy_data(self):
        for lane in (True, 1.5, -1):
            with self.subTest(lane=lane):
                hub = TrafficDataHub(lambdas_module=Lambdas)
                payload = queue_payload(lane=lane)
                self.ingest(DataKind.QUEUE, payload, hub=hub)
                state = VideoExpert(hub).extract(VIDEO_INTERSECTION)
                self.assertEqual(state.observation.queue_map, {})
                self.assertEqual(state.observation.queue_vector, [])
                self.assertIn("queue.car_nums.ycsb_cdbh", state.missing_fields)
                cached = hub.cache.recent_data(DataKind.QUEUE)
                self.assertEqual(cached, [payload])
                self.assertIs(type(cached[0]["car_nums"][0]["ycsb_cdbh"]), type(lane))
                legacy_vector, legacy_map = cache_processor.process_queue_data(cached, Lambdas)
                if lane == -1:
                    self.assertEqual(legacy_map[VIDEO_INTERSECTION], {})
                else:
                    self.assertEqual(legacy_vector[VIDEO_INTERSECTION]["L"][int(lane)], 12)

    def test_unusable_flow_lane_is_not_counted_as_an_observation(self):
        self.ingest(DataKind.FLOW, flow_payload(lane="99"))
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.flow_map, {})
        self.assertEqual(state.observation.traffic_vector, [])
        self.assertIn("flow_map", state.missing_fields)
        self.assertEqual(state.confidence, 0)

    def test_short_flow_window_excludes_its_exact_age_boundary(self):
        self.ingest(DataKind.FLOW, flow_payload(timestamp=1), received_at=NOW - 150)
        self.ingest(DataKind.FLOW, flow_payload(timestamp=2), received_at=NOW - 149.999)
        observation = VideoExpert(self.hub).extract(VIDEO_INTERSECTION).observation
        self.assertEqual(observation.traffic_vector, [2, 0, 0, 0])
        self.assertEqual(observation.traffic_vector_duration2, [1, 0, 0, 0])
        self.assertEqual(
            VideoExpert(self.hub, flow_duration_seconds=100).extract(
                VIDEO_INTERSECTION).observation.traffic_vector_duration2,
            [],
        )

    def test_video_isolates_other_intersections_and_sensor_sources(self):
        self.ingest(DataKind.FLOW, flow_payload(detector="5"))
        self.ingest(DataKind.RADAR, {"deviceNo": RADAR_DEVICE, "speed": 32},
                    source=DataSource.HTTP)
        self.ingest(DataKind.ONLINE, {"rid": next(iter(Lambdas.online_data_map_lambda))})
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(state.observation.traffic_vector, [])
        self.assertEqual(state.observation.radar_map, {})
        self.assertEqual(state.confidence, 0)
        self.assertEqual(
            VideoExpert(self.hub).extract("1300106").observation.traffic_vector,
            [0, 0, 0, 1],
        )

    def test_returned_video_data_cannot_mutate_hub_cache_or_templates(self):
        self.ingest_video_pair()
        before = copy.deepcopy(self.hub.cache.recent_data(DataKind.QUEUE))
        templates = copy.deepcopy(Lambdas.queue_map_single_intersection_lambda)
        state = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        state.observation.queue_map[str(int(NOW))]["queue"]["L"][0] = 777
        state.observation.queue_vector["L"][0] = 777
        again = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        self.assertEqual(again.observation.queue_vector["L"][0], 12)
        self.assertEqual(self.hub.cache.recent_data(DataKind.QUEUE), before)
        self.assertEqual(Lambdas.queue_map_single_intersection_lambda, templates)

    def test_quality_and_truncated_windows_limit_confidence(self):
        self.ingest_video_pair(quality_issues=["device calibration missing"])
        self.assertLessEqual(VideoExpert(self.hub).extract(VIDEO_INTERSECTION).confidence, 0.5)
        bounded = TrafficDataHub(lambdas_module=Lambdas, event_limit=2)
        self.ingest(DataKind.FLOW, flow_payload(), hub=bounded)
        self.ingest_video_pair(hub=bounded)
        self.assertTrue(bounded.query(VIDEO_INTERSECTION, source="video").truncated)
        state = VideoExpert(bounded).extract(VIDEO_INTERSECTION)
        self.assertTrue(state.observation.flow_map)
        self.assertTrue(state.observation.queue_map)
        self.assertLessEqual(state.confidence, 0.5)

    def test_radar_preserves_registered_device_buckets_without_video_vectors(self):
        payload = {"deviceNo": RADAR_DEVICE, "speed": 32}
        self.ingest(DataKind.RADAR, payload, source=DataSource.HTTP)
        expected = cache_processor.process_radar_data([(NOW, payload)], Lambdas)
        state = RadarExpert(self.hub).extract(RADAR_INTERSECTION)
        self.assertEqual(state.source, "radar")
        self.assertEqual(state.observation.radar_map, expected[RADAR_INTERSECTION])
        self.assertEqual(state.observation.traffic_vector, [])
        self.assertEqual(state.observation.queue_vector, [])
        self.assertEqual(state.observation.flow_map, {})
        self.assertEqual(state.observation.queue_map, {})
        self.assertEqual(state.confidence, 1)

    def test_boyan_preserves_direction_and_receipt_timestamp_buckets(self):
        payload = {"deviceId": BOYAN_DEVICE, "value": 4}
        self.ingest(DataKind.BOYAN, payload, source=DataSource.HTTP)
        expected = cache_processor.process_boyan_data([(NOW, payload)], Lambdas)
        state = RadarExpert(self.hub).extract(BOYAN_INTERSECTION)
        self.assertEqual(state.observation.boyan_map, expected[BOYAN_INTERSECTION])
        self.assertEqual(state.observation.boyan_map["U"][int(NOW)][0]["value"], 4)
        self.assertEqual(state.observation.radar_map, {})
        self.assertEqual(state.confidence, 1)

    def test_unregistered_radar_device_does_not_produce_an_observation(self):
        self.ingest(DataKind.RADAR, {"deviceNo": "unknown", "speed": 32},
                    source=DataSource.HTTP)
        state = RadarExpert(self.hub).extract(RADAR_INTERSECTION)
        self.assertEqual(state.observation.radar_map, {})
        self.assertEqual(state.observation.boyan_map, {})
        self.assertIn("radar_map", state.missing_fields)
        self.assertIn("boyan_map", state.missing_fields)
        self.assertEqual(state.confidence, 0)

    def test_radar_ttl_uses_receipt_time_and_includes_exact_boundary(self):
        hub = TrafficDataHub(
            cache=ShortTermMemory({DataKind.RADAR: 10}), lambdas_module=Lambdas,
        )
        self.ingest(DataKind.RADAR, {"deviceNo": RADAR_DEVICE, "createTime": "old"},
                    source=DataSource.HTTP, received_at=NOW - 10, hub=hub)
        self.assertTrue(RadarExpert(hub).extract(RADAR_INTERSECTION).observation.radar_map)
        with patch("time.time", return_value=NOW + 0.001):
            state = RadarExpert(hub).extract(RADAR_INTERSECTION)
            self.assertEqual(state.observation.radar_map, {})
            self.assertEqual(state.confidence, 0)

    def test_overflow_events_remain_missing_without_mutating_legacy_templates(self):
        before = copy.deepcopy(Lambdas.eventMap_Overflow_lambda)
        self.ingest(DataKind.OVERFLOW_WARNING, {
            "distance": 20, "jtll_ddbh": "1", "ts": int(NOW * 1000),
        })
        self.ingest(DataKind.RADAR_EVENT, {
            "deviceNo": RADAR_DEVICE, "eventType": "OverFlow",
            "createTime": "2023-11-14 00:00:00",
        }, source=DataSource.HTTP)
        video = VideoExpert(self.hub).extract(VIDEO_INTERSECTION)
        radar = RadarExpert(self.hub).extract(RADAR_INTERSECTION)
        for state in (video, radar):
            self.assertEqual(state.observation.overflow_map, {})
            self.assertIn("overflow_map", state.missing_fields)
        self.assertEqual(Lambdas.eventMap_Overflow_lambda, before)

    def test_returned_radar_payloads_are_detached_and_quality_limits_confidence(self):
        self.ingest(DataKind.RADAR, {"deviceNo": RADAR_DEVICE, "samples": [32]},
                    source=DataSource.HTTP, quality_issues=["missing calibration"])
        state = RadarExpert(self.hub).extract(RADAR_INTERSECTION)
        state.observation.radar_map[int(NOW)][0]["samples"].append(99)
        again = RadarExpert(self.hub).extract(RADAR_INTERSECTION)
        self.assertEqual(again.observation.radar_map[int(NOW)][0]["samples"], [32])
        self.assertLessEqual(again.confidence, 0.5)
        self.assertEqual(self.hub.cache.recent_data(DataKind.RADAR)[0]["samples"], [32])

    def test_all_experts_validate_intersection_id_before_extracting(self):
        for cls in (VideoExpert, RadarExpert, InternetExpert, EVExpert):
            for invalid in (None, "", "   ", 1300068, True):
                with self.subTest(expert=cls.__name__, intersection_id=invalid):
                    with self.assertRaises((ValueError, TypeError, ValidationError)):
                        cls(self.hub).extract(invalid)

    def test_internet_and_ev_are_explicit_stubs_and_states_carry_no_plan(self):
        for cls in (InternetExpert, EVExpert):
            with self.subTest(expert=cls.__name__):
                with self.assertRaises(NotImplementedError):
                    cls(self.hub).extract(VIDEO_INTERSECTION)
        self.ingest_video_pair()
        output = VideoExpert(self.hub).extract(VIDEO_INTERSECTION).model_dump()
        self.assertEqual(set(output), {"source", "observation", "missing_fields", "confidence"})
        self.assertNotIn("phase_times", output["observation"])
        self.assertNotIn("program_id", output["observation"])


if __name__ == "__main__":
    unittest.main()
