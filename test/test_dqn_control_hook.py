import unittest
from pathlib import Path
from unittest.mock import patch

from lib.control_functions import dqn_control
from lib.control_functions.types import IntersectionControlRequest

ROOT = Path(__file__).resolve().parents[1]


def _request(road_id: str = "1700542") -> IntersectionControlRequest:
    return IntersectionControlRequest(cross_id=road_id, current_time=1762300000.0)


class PilotHookTest(unittest.TestCase):
    def test_dqn_select_no_longer_calls_the_pilot_selector(self):
        source = (ROOT / "lib" / "DQN_Select.py").read_text(encoding="utf-8")
        self.assertNotIn("select_pilot_schedule", source)

    def test_registered_road_goes_through_pilot_selector(self):
        with patch.object(dqn_control, "DQN_select", return_value=([1] * 10, {"c": 1}, {"m": 1}, {"e": 1})), \
                patch.object(dqn_control, "is_enabled", return_value=True), \
                patch.object(dqn_control, "select_pilot_schedule", return_value=[9] * 10) as selector:
            plan, coordinate, model, experience = dqn_control.call_dqn_select(_request())
        selector.assert_called_once()
        self.assertEqual(plan, [9] * 10)
        self.assertEqual((coordinate, model, experience), ({"c": 1}, {"m": 1}, {"e": 1}))

    def test_unregistered_road_keeps_legacy_plan(self):
        with patch.object(dqn_control, "DQN_select", return_value=([1] * 10, {}, {}, {})), \
                patch.object(dqn_control, "is_enabled", return_value=False), \
                patch.object(dqn_control, "select_pilot_schedule") as selector:
            plan, *_ = dqn_control.call_dqn_select(_request("9999999"))
        selector.assert_not_called()
        self.assertEqual(plan, [1] * 10)

    def test_registry_error_falls_back_to_legacy_plan(self):
        with patch.object(dqn_control, "DQN_select", return_value=([2] * 10, {}, {}, {})), \
                patch.object(
                    dqn_control,
                    "is_enabled",
                    side_effect=dqn_control.ControlRegistryError("missing registry"),
                ), \
                patch.object(dqn_control, "select_pilot_schedule") as selector:
            plan, *_ = dqn_control.call_dqn_select(_request())
        selector.assert_not_called()
        self.assertEqual(plan, [2] * 10)

    def test_selector_receives_current_flow_and_extend_maps(self):
        request = _request()
        request.flow_map = {"t1": {"U": 1}}
        request.extend_map = {"t1": {"stage": 2}}
        with patch.object(dqn_control, "DQN_select", return_value=([1] * 10, {}, {}, {})), \
                patch.object(dqn_control, "is_enabled", return_value=True), \
                patch.object(dqn_control, "select_pilot_schedule", return_value=[3] * 10) as selector:
            dqn_control.call_dqn_select(request)
        args = selector.call_args.args
        self.assertEqual(args[0], "1700542")
        self.assertEqual(args[2], request.flow_map)
        self.assertEqual(args[3], request.extend_map)


if __name__ == "__main__":
    unittest.main()
