import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.control.policies import BaselineController
from infra.data import ResultWarehouse
from phase_check import phase_check
from runtime import PeriodicDecisionPipeline


class _Cache:
    def __init__(self):
        self.cleared = False

    def clear_expired(self):
        self.cleared = True

    def size(self, _kind):
        return 0


class _LegacyProcessor:
    def snapshot(self):
        return {kind: [] for kind in ("flow", "queue", "stage", "extend", "online", "radar", "boyan")}

    def online(self):
        return {}

    def stage(self):
        return {"100": {}}

    def extend(self):
        return {"100": {}}

    def boyan(self):
        return {"100": {}}

    def radar(self):
        return {"100": {}}

    def radar_event(self, _event_map, _warning_map):
        return {"100": {}}


class _Lambdas:
    intersection_list = ["100"]
    map_lambda = {"100": {}}
    intersection_flow_lambda = {"100": [0, 0, 0, 0]}
    max_lengths_lambda = {"100": {}}
    intersection_result_lambda = {
        "result_action": [0] * 10,
        "traffic_vector": [],
        "model_info_list": [],
    }


class _Writer:
    def __init__(self):
        self.phase_reports = []
        self.experience = []

    def write_phase_check(self, report):
        self.phase_reports.append(report)

    def write_experience(self, exp_list, intersection_id):
        self.experience.append((exp_list, intersection_id))


class _Predictor:
    def get_current_flow_prediction(self):
        return {}

    def get_current_queue_prediction(self):
        return {}


class PeriodicDecisionPipelineTest(unittest.TestCase):
    def _make_pipeline(self, *, selector=None, coordinator=None, policy=None, writer=None, **kwargs):
        callbacks = {"control_policy": policy} if policy is not None else {
            "dqn_select": selector or (lambda _request: ([10] + [0] * 8 + [1], {}, [], {})),
            "coordinate": coordinator or (lambda action, *_args: action),
        }
        return PeriodicDecisionPipeline(
            cache=_Cache(), data_processor=_LegacyProcessor(), lambdas_module=_Lambdas,
            writer=writer or _Writer(), result_warehouse=ResultWarehouse(),
            flow_predictor=_Predictor(), queue_predictor=_Predictor(),
            phase_check=lambda action: (action, {}),
            select_data_to_send=lambda intersection_id, action, traffic, model: {
                "id": intersection_id, "action": action, "traffic": traffic, "model": model,
            },
            is_millisecond_timestamp=lambda _value: True,
            overflow_warning_map={"100": {}}, radar_event_map={}, flow_duration_seconds=150,
            **callbacks, **kwargs,
        )

    def test_explicit_policy_and_legacy_constructor_produce_identical_results(self):
        raw = ([10.5] + [0] * 8 + [1], {"start": 3}, [1] * 8, {"exp": 1})
        selector = Mock(side_effect=lambda request: raw)
        coordinator = Mock(side_effect=lambda action, *_args: action)
        policy = BaselineController(selector=selector, coordinator=coordinator)
        explicit = self._make_pipeline(policy=policy)
        compatible = self._make_pipeline(selector=selector, coordinator=coordinator)
        with patch("runtime.decision_pipeline.time.time", return_value=1700000000):
            self.assertEqual(explicit.run_once(), compatible.run_once())
        self.assertIs(explicit.control_policy, policy)
        self.assertEqual(len(coordinator.call_args.args), 4)
        self.assertEqual(explicit.last_coordinate_set, compatible.last_coordinate_set)
        self.assertEqual(explicit.writer.experience, compatible.writer.experience)

    def test_selector_failure_keeps_legacy_default_result(self):
        pipeline = self._make_pipeline(selector=Mock(side_effect=RuntimeError("selector failed")))
        result, _, _, _ = pipeline._process_data()
        self.assertEqual(result["100"], _Lambdas.intersection_result_lambda)
        self.assertEqual(pipeline.last_coordinate_set, {"100": {}})
        self.assertEqual(pipeline.writer.experience, [])

    def test_experience_write_failure_keeps_default_result_but_retains_coordinate(self):
        writer = _Writer()
        writer.write_experience = Mock(side_effect=OSError("disk full"))
        pipeline = self._make_pipeline(
            selector=lambda _request: ([30] + [0] * 9, {"start": 3}, [9] * 8, {"exp": 1}),
            writer=writer,
        )
        result, _, _, _ = pipeline._process_data()
        self.assertEqual(result["100"], _Lambdas.intersection_result_lambda)
        self.assertEqual(pipeline.last_coordinate_set, {"100": {"start": 3}})
        writer.write_experience.assert_called_once_with({"exp": 1}, "100")

    def test_failed_finalization_leaves_previous_warehouse_batch(self):
        error = RuntimeError("coordination failed")
        pipeline = self._make_pipeline(coordinator=Mock(side_effect=error))
        pipeline.result_warehouse.replace([{"id": "previous"}])
        with self.assertRaises(RuntimeError) as raised:
            pipeline.run_once()
        self.assertIs(raised.exception, error)
        self.assertEqual(pipeline.result_warehouse.snapshot(), [{"id": "previous"}])
        self.assertEqual(pipeline.writer.phase_reports, [])

    def test_constructor_rejects_ambiguous_policy_and_legacy_callbacks(self):
        policy = BaselineController(selector=Mock(), coordinator=Mock())
        with self.assertRaisesRegex(ValueError, "not both"):
            self._make_pipeline(policy=policy, dqn_select=Mock())

    def test_legacy_callback_attributes_remain_replaceable(self):
        pipeline = self._make_pipeline()
        pipeline.dqn_select = Mock(return_value=([25] + [0] * 9, {}, [], {}))
        pipeline.coordinate = Mock(side_effect=lambda action, *_args: action)
        self.assertEqual(pipeline.run_once()[0]["action"][0], 25)
        pipeline.dqn_select.assert_called_once()
        pipeline.coordinate.assert_called_once()

    def test_legacy_phase_check_still_clamps_reserved_slot(self):
        original = [10] * 8 + [9, 1]
        pipeline = self._make_pipeline(selector=lambda _request: (original, {}, [], {}))
        pipeline.phase_check = phase_check
        with patch("phase_check.intersection_result_config", {"100": {"1": {"8": [3, 6]}}}):
            result = pipeline.run_once()
        self.assertIs(result[0]["action"], original)
        self.assertEqual(original[8], 6)
        self.assertEqual(pipeline.writer.phase_reports[0]["100"]["modifications"], ["Phase 8: 9 -> 6"])

    def test_runs_full_decision_and_updates_result_warehouse(self):
        cache = _Cache()
        writer = _Writer()
        warehouse = ResultWarehouse()
        dqn_calls = []

        def dqn_select(request):
            dqn_calls.append(request)
            return [10, 0, 0, 0, 0, 0, 0, 0, 0, 1], {"coordinate": 1}, [1] * 8, {"exp": 1}

        pipeline = PeriodicDecisionPipeline(
            cache=cache,
            data_processor=_LegacyProcessor(),
            lambdas_module=_Lambdas,
            writer=writer,
            result_warehouse=warehouse,
            flow_predictor=_Predictor(),
            queue_predictor=_Predictor(),
            dqn_select=dqn_select,
            coordinate=lambda action, *_args: action,
            phase_check=lambda action: (action, {"100": {"check_status": 0}}),
            select_data_to_send=lambda intersection_id, action, traffic, model: {
                "id": intersection_id,
                "action": action,
                "traffic": traffic,
                "model": model,
            },
            is_millisecond_timestamp=lambda _value: True,
            overflow_warning_map={"100": {}},
            radar_event_map={},
            flow_duration_seconds=150,
        )

        result = pipeline.run_once()

        self.assertTrue(cache.cleared)
        self.assertEqual(len(dqn_calls), 1)
        self.assertEqual(result, warehouse.snapshot())
        self.assertEqual(result[0]["action"][0], 10)
        self.assertEqual(writer.experience, [({"exp": 1}, "100")])
        self.assertEqual(writer.phase_reports, [{"100": {"check_status": 0}}])

    def test_optional_control_snapshot_preserves_legacy_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline = PeriodicDecisionPipeline(
                cache=_Cache(), data_processor=_LegacyProcessor(), lambdas_module=_Lambdas,
                writer=_Writer(), result_warehouse=ResultWarehouse(),
                flow_predictor=_Predictor(), queue_predictor=_Predictor(),
                dqn_select=lambda _request: ([10] + [0] * 8 + [1], {}, [], {}),
                coordinate=lambda action, *_args: action,
                phase_check=lambda action: (action, {}),
                select_data_to_send=lambda intersection_id, *_args: {"id": intersection_id},
                is_millisecond_timestamp=lambda _value: True,
                overflow_warning_map={"100": {}}, radar_event_map={}, flow_duration_seconds=150,
                control_snapshot_enabled=True, control_snapshot_dir=directory,
            )
            pipeline.run_once()
            files = list(Path(directory).glob("control_*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertIn("coordinate_input", payload)
            self.assertIn("coordinate_map_set", payload)
            self.assertIn("online_map", payload)
            self.assertIn("overflow_map", payload)
            self.assertEqual(payload["extend_map"], {"100": {}})


if __name__ == "__main__":
    unittest.main()
