import unittest
from dataclasses import asdict, fields

from pydantic import TypeAdapter, ValidationError

from app.core.control.adapters import signal_plan_from_legacy, signal_plan_to_legacy
from app.core.control.schemas import SignalPlan
from infra.data.classifier import DataKind, DataSource
from infra.data.traffic_adapters import (
    raw_event_from_legacy, raw_event_to_legacy, snapshot_from_legacy, snapshot_to_legacy,
)
from infra.data.traffic_schemas import ExpertTrafficState, RawTrafficEvent, TrafficSnapshot
from lib.control_functions.types import IntersectionControlRequest


class SignalPlanContractTest(unittest.TestCase):
    def test_round_trip_keeps_fractional_times_zero_gaps_and_program_type(self):
        for program in (0, 2.5, "program-1"):
            legacy = [15.5, 20, 0, 99, 99, 99, 99, 99, 7.5, program]
            with self.subTest(program=program):
                plan = signal_plan_from_legacy("1300068", tuple(legacy))
                self.assertEqual(signal_plan_to_legacy(plan), legacy)
                self.assertIs(type(plan.phase_times[0]), float)
                self.assertIs(type(plan.phase_times[1]), int)
                self.assertIs(type(plan.program_id), type(program))
                self.assertEqual(SignalPlan.model_validate_json(plan.model_dump_json()), plan)

    def test_rejects_malformed_or_coerced_plan(self):
        for value in (-1, True, "15", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                signal_plan_from_legacy("1300068", [value] + [0] * 9)
        for legacy in ([0] * 9, [0] * 11, "0000000000"):
            with self.subTest(legacy=legacy), self.assertRaises(ValueError):
                signal_plan_from_legacy("1300068", legacy)
        for index in (8, 9):
            for value in (True, float("nan"), float("inf")):
                legacy = [0] * 10
                legacy[index] = value
                with self.subTest(index=index, value=value), self.assertRaises(ValidationError):
                    signal_plan_from_legacy("1300068", legacy)

    def test_enforces_identity_shape_and_extra_fields(self):
        valid = signal_plan_from_legacy("1300068", [0] * 10).model_dump()
        for patch in ({"intersection_id": " "}, {"intersection_id": 1300068},
                      {"phase_times": (0,) * 7}, {"phase_times": (0,) * 9},
                      {"approved_by_llm": True}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                SignalPlan.model_validate(valid | patch)


class TrafficStateContractTest(unittest.TestCase):
    def test_reuses_all_legacy_fields_without_mutating_requests(self):
        request = IntersectionControlRequest(
            cross_id="1300068", current_time=1700000000,
            traffic_vector=[1, 2, 3, 4], queue_vector={"L": [12, 0, 0, 0, 0, 0, 0]},
            stage_map={1700000000: {"curStageNo": 3, "curStageLen": 19}},
            extend_map={1700000000.5: [{"CrossId": "1300068", "curStageRemainLen": 8}]},
        )
        snapshot = snapshot_from_legacy(request)
        self.assertEqual({f.name for f in fields(snapshot)}, {f.name for f in fields(request)})
        restored = snapshot_to_legacy(snapshot)
        self.assertIs(type(restored), IntersectionControlRequest)
        self.assertEqual(asdict(restored), asdict(request))
        self.assertEqual(snapshot.intersection_id, request.cross_id)
        restored.stage_map[1700000000]["curStageNo"] = 7
        snapshot.queue_vector["L"][0] = 99
        self.assertEqual(request.stage_map[1700000000]["curStageNo"], 3)
        self.assertEqual(request.queue_vector["L"][0], 12)

    def test_empty_legacy_list_and_direction_dictionary_are_both_accepted(self):
        for queue in ([], {}, {"L": [0] * 7}):
            with self.subTest(queue=queue):
                snapshot = TrafficSnapshot(cross_id="1300068", current_time=1, queue_vector=queue)
                self.assertEqual(snapshot.queue_vector, queue)

    def test_snapshot_rejects_invalid_envelope_and_top_level_state_shapes(self):
        valid = {"cross_id": "1300068", "current_time": 1}
        for patch in ({"cross_id": " "}, {"cross_id": 123}, {"current_time": "1"},
                      {"current_time": True}, {"current_time": float("nan")},
                      {"current_time": -1}, {"queue_vector": "missing"},
                      {"flow_map": []}, {"traffic_vector": "1234"}, {"plan": [0] * 10}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                TrafficSnapshot(**(valid | patch))
        # 旧 dataclass 仍不执行边界校验，生产路径未被新契约悄悄接管。
        self.assertEqual(IntersectionControlRequest(cross_id=123, current_time="1").cross_id, 123)

    def test_expert_state_carries_quality_but_cannot_add_a_plan(self):
        snapshot = TrafficSnapshot(cross_id="1300068", current_time=1)
        valid = {"source": "video", "observation": snapshot,
                 "confidence": 0.5, "missing_fields": ["flow_map"]}
        state = ExpertTrafficState(**valid)
        self.assertEqual(state.observation.intersection_id, "1300068")
        for patch in ({"confidence": -0.1}, {"confidence": 1.1}, {"confidence": "0.5"},
                      {"confidence": True}, {"source": "other"}, {"signal_plan": [0] * 10}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                ExpertTrafficState(**(valid | patch))
        restored = ExpertTrafficState.model_validate_json(state.model_dump_json())
        self.assertEqual(asdict(restored.observation), asdict(snapshot))

    def test_contracts_export_strict_json_schemas(self):
        for contract in (RawTrafficEvent, TrafficSnapshot, ExpertTrafficState, SignalPlan):
            with self.subTest(contract=contract):
                self.assertFalse(TypeAdapter(contract).json_schema()["additionalProperties"])


class RawTrafficEventContractTest(unittest.TestCase):
    def test_raw_payload_and_timestamp_units_remain_unchanged(self):
        payload = {"ycsb_xsfx": "L", "jtll_ddbh": "1", "ycsb_cdbh": "0",
                   "ts": "1700000000000", "vendor": {"opaque": [1, 2]}}
        event = raw_event_from_legacy(payload, source=DataSource.TCP,
                                      received_at=1700000001.5, intersection_id="1300068")
        self.assertEqual(event.kind, DataKind.FLOW)
        self.assertEqual(event.quality_issues, [])
        self.assertEqual(event.received_at, 1700000001.5)
        self.assertEqual(raw_event_to_legacy(event), payload)
        event.payload["vendor"]["opaque"].append(3)
        self.assertEqual(payload["vendor"]["opaque"], [1, 2])
        restored = raw_event_to_legacy(event)
        restored["vendor"]["opaque"].clear()
        self.assertEqual(event.payload["vendor"]["opaque"], [1, 2, 3])

    def test_incomplete_payload_retains_nonblocking_quality_issues(self):
        payload = {"car_nums": [], "jtll_ddbh": "1", "start_time": "bad"}
        event = raw_event_from_legacy(payload, source=DataSource.TCP, received_at=1)
        self.assertEqual(event.payload, payload)
        self.assertEqual(event.quality_issues, ["时间字段不是整数时间戳: start_time"])
        missing = raw_event_from_legacy({"ycsb_xsfx": "L"}, source=DataSource.TCP, received_at=1)
        self.assertIn("缺少字段: ts", missing.quality_issues)

    def test_classification_precedence_http_and_unknown_payloads(self):
        for source, payload, kind in (
            (DataSource.TCP, {"ycsb_xsfx": "L", "car_nums": []}, DataKind.FLOW),
            (DataSource.HTTP, {"deviceNo": "radar", "eventType": None}, DataKind.RADAR),
            (DataSource.HTTP, {"deviceNo": "radar", "eventType": "OverFlow"}, DataKind.RADAR_EVENT),
            (DataSource.HTTP, {"deviceId": "boyan"}, DataKind.BOYAN),
            (DataSource.HTTP, {"vendor": "unknown"}, DataKind.HISTORY),
        ):
            with self.subTest(payload=payload):
                event = raw_event_from_legacy(payload, source=source, received_at=1)
                self.assertEqual(event.kind, kind)
                self.assertEqual(event.payload, payload)

    def test_raw_envelope_rejects_coercion_and_extra_fields(self):
        valid = {"kind": DataKind.HISTORY, "source": DataSource.TCP,
                 "received_at": 1, "payload": {}}
        for patch in ({"received_at": "1"}, {"received_at": True},
                      {"received_at": float("inf")}, {"source": "tcp"},
                      {"payload": []}, {"intersection_id": " "}, {"green_time": 37}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                RawTrafficEvent(**(valid | patch))
