import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from pydantic import ValidationError

from app.core.control.adapters import signal_plan_to_legacy
from app.core.control.policies import BaselineController
from infra.data.traffic_schemas import TrafficSnapshot
from lib.control_functions.types import IntersectionControlRequest


class BaselineControllerTest(unittest.TestCase):
    def test_compatibility_entry_preserves_request_result_and_diagnostic_references(self):
        request = IntersectionControlRequest(cross_id="1300068", current_time=1)
        raw = ([15.5, 20, 0, 99, 0, 0, 0, 0, 7, 2], {"s1": 3}, [1] * 8, [])
        selector = Mock(return_value=raw)
        controller = BaselineController(selector=selector, coordinator=Mock())
        result = controller.select_legacy(request)
        self.assertIs(selector.call_args.args[0], request)
        self.assertIs(result, raw)
        for original, returned in zip(raw, result):
            self.assertIs(original, returned)

    def test_typed_prediction_preserves_fractional_times_and_isolates_snapshot(self):
        snapshot = TrafficSnapshot(cross_id="1300068", current_time=1,
                                   flow_map={1.5: {"counts": [3]}})
        legacy = [15.5, 20, 0, 99, 0, 0, 0, 0, 7, 2]

        def select(request):
            self.assertIs(type(request), IntersectionControlRequest)
            request.flow_map[1.5]["counts"].append(9)
            return legacy, {}, [], {}

        selector = Mock(side_effect=select)
        controller = BaselineController(selector=selector, coordinator=Mock())
        prediction = controller.predict(snapshot)
        self.assertEqual(prediction.intersection_id, snapshot.intersection_id)
        self.assertEqual(signal_plan_to_legacy(prediction), legacy)
        self.assertEqual(snapshot.flow_map[1.5]["counts"], [3])
        self.assertEqual(selector.call_count, 1)

    def test_strict_prediction_rejects_wrong_state_and_invalid_candidate_without_fallback(self):
        selector = Mock(return_value=([-1] + [0] * 9, {}, [], {}))
        controller = BaselineController(selector=selector, coordinator=Mock())
        with self.assertRaises(ValidationError):
            controller.predict(IntersectionControlRequest(cross_id="1300068", current_time=1))
        selector.assert_not_called()
        snapshot = TrafficSnapshot(cross_id="1300068", current_time=1)
        with self.assertRaises(ValidationError):
            controller.predict(snapshot)
        self.assertEqual(controller.select_legacy(snapshot)[0][0], -1)

    def test_selector_and_coordinator_errors_propagate_unchanged(self):
        error = RuntimeError("legacy failure")
        controller = BaselineController(selector=Mock(side_effect=error), coordinator=Mock(side_effect=error))
        request = IntersectionControlRequest(cross_id="1300068", current_time=1)
        for invoke in (lambda: controller.select_legacy(request),
                       lambda: controller.predict(TrafficSnapshot(cross_id="1300068", current_time=1)),
                       lambda: controller.coordinate_legacy({}, {}, {}, {})):
            with self.assertRaises(RuntimeError) as raised:
                invoke()
            self.assertIs(raised.exception, error)

    def test_coordination_retains_four_arguments_and_in_place_mutation(self):
        plan = [10] + [0] * 9
        action, previous, online, overflow = {"1300068": plan}, {}, {}, {}

        def coordinate(*args):
            self.assertEqual(len(args), 4)
            for received, original in zip(args, (action, previous, online, overflow)):
                self.assertIs(received, original)
            args[0]["1300068"][0] = 15.5
            return args[0]

        controller = BaselineController(selector=Mock(), coordinator=coordinate)
        self.assertIs(controller.coordinate_legacy(action, previous, online, overflow), action)
        self.assertIs(action["1300068"], plan)
        self.assertEqual(plan[0], 15.5)

    def test_shared_controller_returns_each_intersections_own_diagnostics(self):
        def select(request):
            return [int(request.cross_id)] + [0] * 9, {"id": request.cross_id}, [request.cross_id], {"id": request.cross_id}

        controller = BaselineController(selector=select, coordinator=Mock())
        requests = [IntersectionControlRequest(cross_id=str(i), current_time=1) for i in range(1, 65)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(controller.select_legacy, requests))
        for request, (plan, coordinate, model, experience) in zip(requests, results):
            self.assertEqual(plan[0], int(request.cross_id))
            self.assertEqual(coordinate["id"], request.cross_id)
            self.assertEqual(model, [request.cross_id])
            self.assertEqual(experience["id"], request.cross_id)

    def test_controller_and_runtime_can_be_imported_in_either_order(self):
        for imports in ("from app.core.control.policies import BaselineController; import runtime",
                        "import runtime; from app.core.control.policies import BaselineController"):
            with self.subTest(imports=imports):
                result = subprocess.run([sys.executable, "-c", imports], capture_output=True,
                                        text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
