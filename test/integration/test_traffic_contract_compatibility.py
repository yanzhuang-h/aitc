import copy
import io
import json
import random
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import Lambdas

from app.core.control.adapters import (
    signal_plan_from_legacy, signal_plan_to_legacy, signal_plan_to_payload,
)
from infra.data import ResultSender, ResultWarehouse
from infra.data.traffic_adapters import snapshot_from_legacy, snapshot_to_legacy
from lib.control_functions.dqn_control import call_dqn_select
from lib.control_functions.types import IntersectionControlRequest
from phase_check import phase_check
from runtime.result_formatter import format_result


class _Socket:
    def __init__(self):
        self.frames = []

    def sendall(self, frame):
        self.frames.append(frame)


class TrafficContractCompatibilityTest(unittest.TestCase):
    def test_real_timetable_rule_selector_and_phase_check_remain_equivalent(self):
        root = Path(__file__).resolve().parents[2]
        timetable = json.loads((root / "time_schedule/schedule_json/Time_schedule_1300103.json").read_text())
        request = IntersectionControlRequest(
            cross_id="1300103", current_time=1700000000,
            traffic_vector=[3, 4, 5, 6], traffic_vector_duration2=[1, 2, 3, 4],
            queue_vector={direction: [0] * 7 for direction in "LRUD"},
        )
        saved = random.getstate()
        try:
            with (
                patch("lib.DQN_Select.Get_time_map", side_effect=lambda _id: copy.deepcopy(timetable)),
                redirect_stdout(io.StringIO()),
            ):
                random.seed(37)
                legacy = call_dqn_select(copy.deepcopy(request))
                random.seed(37)
                adapted = call_dqn_select(snapshot_to_legacy(snapshot_from_legacy(request)))
        finally:
            random.setstate(saved)
        self.assertEqual(adapted, legacy)
        legacy_checked, legacy_report = phase_check({request.cross_id: list(legacy[0])})
        plan = signal_plan_from_legacy(request.cross_id, adapted[0])
        adapted_checked, adapted_report = phase_check({request.cross_id: signal_plan_to_legacy(plan)})
        self.assertEqual(adapted_checked, legacy_checked)
        self.assertEqual(adapted_report, legacy_report)
        final_plan = signal_plan_from_legacy(request.cross_id, adapted_checked[request.cross_id])
        self.assertEqual(
            signal_plan_to_payload(final_plan, request.traffic_vector, adapted[2], lambdas_module=Lambdas),
            format_result(request.cross_id, legacy_checked[request.cross_id], request.traffic_vector,
                          legacy[2], lambdas_module=Lambdas),
        )

    def test_frozen_legacy_payloads_survive_plan_adapters_warehouse_and_sender(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures/v2_signal_plan_baseline.json"
        cases = json.loads(fixture.read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["name"]):
                original = list(case["plan"])
                plan = signal_plan_from_legacy(case["intersection_id"], original)
                self.assertEqual(signal_plan_to_legacy(plan), original)
                payload = signal_plan_to_payload(
                    plan, case["traffic_vector"], case["model_info_list"], lambdas_module=Lambdas,
                )
                self.assertEqual(payload, case["expected_payload"])
                self.assertEqual(original, case["plan"])
                warehouse = ResultWarehouse()
                warehouse.replace([payload])
                client = _Socket()
                self.assertEqual(ResultSender().send_batch([client], warehouse.snapshot()), [])
                self.assertEqual(client.frames, [(json.dumps(case["expected_payload"]) + "\n").encode()])

    def test_default_model_info_preserves_seeded_random_output(self):
        legacy = [42, 18, 44, 0, 0, 0, 0, 0, 0, 0]
        saved = random.getstate()
        try:
            random.seed(37)
            expected = format_result("1300068", legacy, [0] * 4, [], lambdas_module=Lambdas)
            random.seed(37)
            result = signal_plan_to_payload(signal_plan_from_legacy("1300068", legacy),
                                            [0] * 4, [], lambdas_module=Lambdas)
        finally:
            random.setstate(saved)
        self.assertEqual(result, expected)
