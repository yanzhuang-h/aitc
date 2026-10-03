"""DataHub 边界、路口隔离和旧缓存兼容行为。"""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from infra.data.classifier import ClassifiedData, DataKind, DataSource
from infra.data.datahub import TrafficDataHub
from infra.data.memory.short_term import ShortTermMemory
from infra.data.traffic_schemas import RawTrafficEvent
from lib.control_functions.types import IntersectionControlRequest


NOW = 1_000.0


def mappings():
    return SimpleNamespace(
        intersection_list=["A", "B"],
        aibi_to_xinkongji={"15": "A"},
        location_to_intersection_lambda={101: ("15", "D")},
        online_data_map_lambda={"shared-road": {}, "unmapped-road": {}},
        latest_data_map_lambda={"map-node": {}, "A": {}},
        intersection_to_rid_lambda={
            "A": [("shared-road", None)],
            "B": [("shared-road", "D")],
        },
        device_to_location={"radar-1": ("15", "D")},
        boyan_device_to_location={"boyan-1": ("B", "U")},
        radar_event_list=["queue"],
    )


def event(kind=DataKind.STAGE, *, intersection_id="A", source=DataSource.TCP,
          received_at=NOW, payload=None):
    if payload is None:
        payload = {
            "CrossId": intersection_id, "time": NOW,
            "curStageNo": 1, "curStageLen": 30,
        }
    return RawTrafficEvent(
        kind=kind, source=source, received_at=received_at,
        intersection_id=intersection_id, payload=payload,
    )


def request(intersection_id="A", current_time=NOW):
    return IntersectionControlRequest(
        cross_id=intersection_id, current_time=current_time,
        traffic_vector=[3, 4], queue_vector={"D": [2]},
        flow_map={NOW: {"D": {"count": 3}}},
        previous_coordinate={"A": {"extend": [5]}},
    )


def deep_json():
    return json.loads('{"vendor":' * 500 + '0' + '}' * 500)


class TrafficDataHubTest(unittest.TestCase):
    def setUp(self):
        self.clock = patch("time.time", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.cache = ShortTermMemory()
        self.hub = TrafficDataHub(
            cache=self.cache, lambdas_module=mappings(), memory_window=3,
        )

    def test_configuration_requires_positive_integer_bounds(self):
        for field in ("memory_window", "event_limit"):
            for value in (0, -1, True, 1.5, "2"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises((TypeError, ValueError, ValidationError)):
                        TrafficDataHub(**{field: value})

    def test_ingest_revalidates_even_an_existing_model(self):
        invalid = event().model_copy(update={"received_at": float("nan")})
        with self.assertRaises(ValidationError):
            self.hub.ingest(invalid)
        self.assertEqual(self.cache.size(DataKind.STAGE), 0)
        self.assertEqual(self.hub.query("A").events, [])

    def test_ingest_rejects_a_kind_that_disagrees_with_the_payload(self):
        invalid = event().model_copy(update={"kind": DataKind.FLOW})
        with self.assertRaises((ValidationError, ValueError)):
            self.hub.ingest(invalid)
        self.assertEqual(self.cache.size(DataKind.STAGE), 0)
        self.assertEqual(self.cache.size(DataKind.FLOW), 0)

    def test_event_storage_and_reads_do_not_expose_nested_mutable_state(self):
        original = event(payload={
            "CrossId": "A", "time": NOW, "curStageNo": 1,
            "curStageLen": 30, "nested": {"samples": [1]},
        })
        self.hub.ingest(original)
        original.payload["nested"]["samples"].append(2)
        view = self.hub.query("A")
        self.assertEqual(view.events[0].payload["nested"]["samples"], [1])
        view.events[0].payload["nested"]["samples"].append(3)
        self.assertEqual(
            self.hub.query("A").events[0].payload["nested"]["samples"], [1],
        )

    def test_round_history_is_bounded_and_isolated_by_intersection(self):
        for offset in range(5):
            self.hub.capture(request("A", NOW + offset))
        self.hub.capture(request("B", NOW + 10))
        self.assertEqual(
            [item.current_time for item in self.hub.history("A")],
            [NOW + 2, NOW + 3, NOW + 4],
        )
        self.assertEqual(self.hub.latest("A").current_time, NOW + 4)
        self.assertEqual(len(self.hub.history("B")), 1)
        self.assertIsNone(self.hub.latest("unknown"))
        self.assertEqual(self.hub.history("unknown"), [])

    def test_capture_and_all_snapshot_reads_are_deep_copies(self):
        original = request()
        captured = self.hub.capture(original)
        original.flow_map[NOW]["D"]["count"] = 99
        original.previous_coordinate["A"]["extend"].append(99)
        captured.queue_vector["D"].append(99)
        latest = self.hub.latest("A")
        self.assertEqual(latest.flow_map[NOW]["D"]["count"], 3)
        self.assertEqual(latest.previous_coordinate["A"]["extend"], [5])
        self.assertEqual(latest.queue_vector["D"], [2])
        latest.traffic_vector.append(99)
        history = self.hub.history("A")
        history[0].flow_map[NOW]["D"]["count"] = 88
        queried = self.hub.query("A").snapshot
        queried.queue_vector["D"].append(88)
        self.assertEqual(self.hub.latest("A").traffic_vector, [3, 4])
        self.assertEqual(self.hub.latest("A").flow_map[NOW]["D"]["count"], 3)
        self.assertEqual(self.hub.latest("A").queue_vector["D"], [2])

    def test_history_limit_selects_recent_rounds_in_chronological_order(self):
        for offset in range(3):
            self.hub.capture(request(current_time=NOW + offset))
        self.assertEqual(
            [item.current_time for item in self.hub.history("A", limit=2)],
            [NOW + 1, NOW + 2],
        )
        self.assertEqual(self.hub.history("A", limit=0), [])
        self.assertEqual(len(self.hub.history("A", limit=99)), 3)
        for value in (-1, True, 1.5, "2"):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError, ValidationError)):
                    self.hub.history("A", limit=value)

    def test_invalid_snapshot_does_not_replace_last_valid_round(self):
        self.hub.capture(request())
        invalid = request(current_time=float("nan"))
        self.assertIsNone(self.hub.capture(invalid))
        self.assertEqual(self.hub.latest("A").current_time, NOW)
        self.assertEqual(len(self.hub.history("A")), 1)
        self.assertTrue(self.hub.query("A").quality_issues)
        self.assertNotEqual(invalid.current_time, invalid.current_time)

    def test_missing_state_and_ev_source_are_explicit(self):
        missing = self.hub.query("A")
        self.assertIn("events", missing.missing_fields)
        self.assertIn("snapshot", missing.missing_fields)
        self.hub.capture(request())
        self.hub.ingest(event())
        absent_ev = self.hub.query("A", source="ev")
        self.assertEqual(absent_ev.events, [])
        self.assertIn("events", absent_ev.missing_fields)
        self.assertEqual(absent_ev.source, "ev")

    def test_domain_source_and_transport_filters_are_independent(self):
        self.hub.ingest(event())
        self.hub.ingest(event(
            DataKind.RADAR, source=DataSource.HTTP,
            payload={"deviceNo": "radar-1", "nested": {"speed": [10]}},
        ))
        self.hub.ingest(event(
            DataKind.ONLINE, payload={"rid": "shared-road"},
        ))
        self.assertEqual(
            [item.kind for item in self.hub.query("A", "video").events],
            [DataKind.STAGE],
        )
        self.assertEqual(
            [item.kind for item in self.hub.query("A", "radar").events],
            [DataKind.RADAR],
        )
        self.assertEqual(
            [item.kind for item in self.hub.query("A", "internet").events],
            [DataKind.ONLINE],
        )
        self.assertEqual(
            [item.source for item in self.hub.query("A", transport=DataSource.HTTP).events],
            [DataSource.HTTP],
        )
        self.assertEqual(
            self.hub.query("A", "radar", transport=DataSource.TCP).events, [],
        )
        self.assertEqual(
            [item.kind for item in self.hub.query("A", kind=DataKind.STAGE).events],
            [DataKind.STAGE],
        )

    def test_query_expires_by_receipt_time_with_inclusive_window_boundary(self):
        cache = ShortTermMemory({DataKind.STAGE: 10})
        hub = TrafficDataHub(cache=cache, lambdas_module=mappings())
        hub.ingest(event(received_at=NOW - 10, payload={
            "CrossId": "A", "time": 0, "curStageNo": 1, "curStageLen": 30,
        }))
        self.assertEqual(len(hub.query("A").events), 1)
        self.assertEqual(cache.recent_legacy_tuples(DataKind.STAGE)[0][0], NOW - 10)
        with patch("time.time", return_value=NOW + 0.001):
            self.assertEqual(hub.query("A").events, [])
            self.assertEqual(cache.recent_data(DataKind.STAGE), [])

    def test_query_event_limit_does_not_truncate_the_legacy_cache(self):
        hub = TrafficDataHub(
            cache=self.cache, lambdas_module=mappings(), event_limit=2,
        )
        for stage in range(3):
            hub.ingest(event(payload={
                "CrossId": "A", "time": NOW,
                "curStageNo": stage, "curStageLen": 30,
            }))
        view = hub.query("A")
        self.assertEqual([item.payload["curStageNo"] for item in view.events], [1, 2])
        self.assertTrue(view.truncated)
        self.assertEqual(self.cache.size(DataKind.STAGE), 3)

    def test_detector_mapping_and_alias_identify_the_control_intersection(self):
        self.hub.ingest_classified(ClassifiedData(
            DataKind.FLOW,
            {"ycsb_xsfx": "D", "jtll_ddbh": 101, "ycsb_cdbh": 1, "ts": NOW},
            DataSource.TCP,
        ))
        self.hub.ingest_classified(ClassifiedData(
            DataKind.STAGE,
            {"CrossId": "15", "time": NOW, "curStageNo": 1, "curStageLen": 30},
            DataSource.TCP,
        ))
        self.assertEqual(
            [item.intersection_id for item in self.hub.query("A").events], ["A", "A"],
        )
        self.assertEqual(self.hub.query("15").events, [])
        self.assertEqual(self.hub.query("B").events, [])

    def test_shared_internet_road_is_visible_at_every_mapped_intersection(self):
        self.hub.ingest_classified(ClassifiedData(
            DataKind.ONLINE, {"rid": "shared-road", "speed": [10]}, DataSource.TCP,
        ))
        a = self.hub.query("A", "internet")
        b = self.hub.query("B", "internet")
        self.assertEqual(len(a.events), 1)
        self.assertEqual(len(b.events), 1)
        self.assertEqual(a.events[0].intersection_id, "A")
        self.assertEqual(b.events[0].intersection_id, "B")
        a.events[0].payload["speed"].append(99)
        self.assertEqual(self.hub.query("B").events[0].payload["speed"], [10])

    def test_latest_map_node_is_unassociated_instead_of_becoming_an_intersection(self):
        self.hub.ingest_classified(ClassifiedData(
            DataKind.LATEST, {"inter_id": "map-node"}, DataSource.TCP,
        ))
        unassociated = self.hub.query(None, "internet")
        self.assertEqual(len(unassociated.events), 1)
        self.assertIsNone(unassociated.events[0].intersection_id)
        self.assertTrue(unassociated.quality_issues)
        self.assertEqual(self.hub.query("map-node").events, [])
        self.assertEqual(self.cache.size(DataKind.LATEST), 1)

    def test_radar_boyan_and_event_devices_use_their_existing_location_maps(self):
        radar_events = {"queue": {}}
        hub = TrafficDataHub(
            cache=self.cache, lambdas_module=mappings(), radar_event_map=radar_events,
        )
        hub.ingest_classified(ClassifiedData(
            DataKind.RADAR, {"deviceNo": "radar-1"}, DataSource.HTTP,
        ))
        hub.ingest_classified(ClassifiedData(
            DataKind.BOYAN, {"deviceId": "boyan-1"}, DataSource.HTTP,
        ))
        event_payload = {"deviceNo": "radar-1", "eventType": "queue"}
        hub.ingest_classified(ClassifiedData(
            DataKind.RADAR_EVENT, event_payload, DataSource.HTTP,
        ))
        self.assertEqual(
            [item.kind for item in hub.query("A", "radar").events],
            [DataKind.RADAR, DataKind.RADAR_EVENT],
        )
        self.assertEqual(
            [item.kind for item in hub.query("B", "radar").events], [DataKind.BOYAN],
        )
        self.assertIs(radar_events["queue"]["radar-1"], event_payload)
        self.assertEqual(self.cache.size(DataKind.RADAR), 1)
        self.assertEqual(self.cache.size(DataKind.BOYAN), 1)

    def test_legacy_malformed_payload_is_not_filtered_or_rewritten(self):
        payload = {
            "CrossId": "A", "curStageLen": "invalid",
            "nested": {"samples": [1]},
        }
        self.hub.ingest_classified(ClassifiedData(DataKind.STAGE, payload, DataSource.TCP))
        cached = self.cache.recent_data(DataKind.STAGE)
        self.assertIs(cached[0], payload)
        self.assertEqual(cached[0]["curStageLen"], "invalid")
        view = self.hub.query("A", "video")
        self.assertEqual(view.events[0].payload, payload)
        self.assertTrue(view.events[0].quality_issues)
        payload["nested"]["samples"].append(2)
        self.assertEqual(view.events[0].payload["nested"]["samples"], [1])
        self.assertEqual(self.hub.query("A").events[0].payload["nested"]["samples"], [1])

    def test_infinite_detector_id_does_not_block_legacy_cache_admission(self):
        payload = {"ycsb_xsfx": "D", "jtll_ddbh": float("inf"), "ycsb_cdbh": 1, "ts": NOW}
        self.hub.ingest_classified(ClassifiedData(DataKind.FLOW, payload, DataSource.TCP))
        self.assertIs(self.cache.recent_data(DataKind.FLOW)[0], payload)
        self.assertEqual(len(self.hub.query(None).events), 1)
        self.assertIn("intersection_unresolved", self.hub.query(None).quality_issues)

    def test_unknown_intersection_ids_share_a_bounded_unassociated_partition(self):
        hub = TrafficDataHub(cache=self.cache, lambdas_module=mappings(), event_limit=3)
        for index in range(100):
            hub.ingest_classified(ClassifiedData(
                DataKind.STAGE, {"CrossId": f"unknown-{index}", "time": NOW,
                                "curStageNo": 1, "curStageLen": 30}, DataSource.TCP,
            ))
            self.assertIsNone(hub.capture(request(f"unknown-{index}")))
        self.assertEqual(len(hub.query(None).events), 3)
        self.assertEqual(self.cache.size(DataKind.STAGE), 100)
        # 验证实际分配也有界，不能仅从返回空列表推断内存已释放。
        self.assertEqual(set(hub._events), {None})
        self.assertEqual(hub._history, {})
        self.assertEqual(set(hub._snapshot_issues), {None})

    def test_expired_unqueried_partitions_are_released_during_global_cleanup(self):
        self.hub.ingest(event(intersection_id="A"))
        self.hub.ingest(event(intersection_id="B"))
        with patch("time.time", return_value=NOW + 601):
            self.hub.query(None)
        self.assertEqual(self.hub._events, {})

    def test_strict_ingest_rejects_out_of_order_receipt_before_cache_mutation(self):
        self.hub.ingest(event())
        with self.assertRaises(ValueError):
            self.hub.ingest(event(received_at=NOW - 1))
        self.assertEqual([stamp for stamp, _ in self.cache.recent_legacy_tuples(DataKind.STAGE)], [NOW])
        self.assertEqual([item.received_at for item in self.hub.query("A").events], [NOW])

    def test_future_receipt_is_rejected_without_corrupting_mixed_ingress_windows(self):
        with self.assertRaises(ValueError):
            self.hub.ingest(event(received_at=NOW + 1000))
        self.hub.ingest_classified(ClassifiedData(
            DataKind.STAGE, {"CrossId": "A", "curStageLen": 30}, DataSource.TCP,
        ))
        with self.assertRaises(ValueError):
            self.hub.ingest(event(received_at=NOW + 500))
        with patch("time.time", return_value=NOW + 601):
            self.assertEqual(self.hub.query("A").events, [])
            self.assertEqual(self.cache.recent_data(DataKind.STAGE), [])

    def test_clock_rollback_does_not_reset_strict_ingress_monotonicity(self):
        self.hub.ingest(event())
        with patch("time.time", return_value=NOW - 1):
            self.hub.ingest_classified(ClassifiedData(
                DataKind.STAGE, {"CrossId": "A", "curStageLen": 30}, DataSource.TCP,
            ))
            with self.assertRaises(ValueError):
                self.hub.ingest(event(received_at=NOW - 1))
        self.assertEqual(self.cache.size(DataKind.STAGE), 2)

    def test_unhashable_metadata_is_retained_without_new_legacy_errors(self):
        hub = TrafficDataHub(cache=self.cache)
        hub.ingest_classified(ClassifiedData(DataKind.ONLINE, {"rid": [1]}, DataSource.TCP))
        self.assertEqual(hub.query(None).events[0].payload, {"rid": [1]})
        self.assertEqual(self.cache.size(DataKind.ONLINE), 0)

    def test_deep_json_copy_failure_preserves_legacy_cache_and_reports_quality(self):
        payload = {"CrossId": "A", "curStageLen": 30, "vendor": deep_json()}
        json.dumps(payload)
        self.hub.ingest_classified(ClassifiedData(DataKind.STAGE, payload, DataSource.TCP))
        self.assertIs(self.cache.recent_data(DataKind.STAGE)[0], payload)
        view = self.hub.query("A")
        self.assertIn("event_capture", view.missing_fields)
        self.assertTrue(any("RecursionError" in issue for issue in view.quality_issues))
        with patch("time.time", return_value=NOW + 601):
            self.assertNotIn("event_capture", self.hub.query("A").missing_fields)

    def test_strict_deep_copy_failure_does_not_write_to_legacy_cache(self):
        incoming = event(payload={"CrossId": "A", "curStageLen": 30, "vendor": deep_json()})
        with self.assertRaises(RecursionError):
            self.hub.ingest(incoming)
        self.assertEqual(self.cache.size(DataKind.STAGE), 0)

    def test_deep_snapshot_copy_failure_retains_previous_valid_round(self):
        self.hub.capture(request())
        incoming = request()
        incoming.predicted_flow = {"vendor": deep_json()}
        self.assertIsNone(self.hub.capture(incoming))
        self.assertEqual(len(self.hub.history("A")), 1)
        self.assertTrue(any("snapshot_capture_failed" in issue for issue in self.hub.query("A").quality_issues))

    def test_unmapped_device_is_retained_with_quality_without_changing_cache_admission(self):
        payload = {"deviceNo": "unknown-device"}
        self.hub.ingest_classified(ClassifiedData(DataKind.RADAR, payload, DataSource.HTTP))
        self.assertEqual(self.cache.size(DataKind.RADAR), 0)
        view = self.hub.query(None, "radar")
        self.assertEqual(view.events[0].payload, payload)
        self.assertTrue(view.quality_issues)

    def test_concurrent_round_capture_and_query_preserve_bounded_isolated_history(self):
        def capture_and_query(index):
            intersection_id = "A" if index % 2 else "B"
            self.hub.capture(request(intersection_id, NOW + index))
            self.hub.ingest(event(intersection_id=intersection_id))
            view = self.hub.query(intersection_id)
            self.assertEqual(view.snapshot.cross_id, intersection_id)
            self.assertTrue(all(item.intersection_id == intersection_id for item in view.events))
            self.assertLessEqual(len(self.hub.history(intersection_id)), 3)

        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(capture_and_query, range(40)))
        for intersection_id in ("A", "B"):
            history = self.hub.history(intersection_id)
            self.assertEqual(len(history), 3)
            self.assertTrue(all(item.cross_id == intersection_id for item in history))


if __name__ == "__main__":
    unittest.main()
