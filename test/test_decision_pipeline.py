import unittest

from infra.data import ResultWarehouse
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
    def test_runs_full_decision_and_updates_result_warehouse(self):
        cache = _Cache()
        writer = _Writer()
        warehouse = ResultWarehouse()
        dqn_calls = []

        def dqn_select(*args):
            dqn_calls.append(args)
            return [10, 0, 0, 0, 0, 0, 0, 0, 0, 1], {"coordinate": 1}, [1] * 8, {"exp": 1}

        pipeline = PeriodicDecisionPipeline(
            cache=cache,
            legacy_processor=_LegacyProcessor(),
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


if __name__ == "__main__":
    unittest.main()
