"""Golden equivalence at the real selector, global control and TCP boundaries."""

import copy
import json
import random
import unittest
from unittest.mock import patch

from app.core.control.adapters import signal_plan_to_legacy
from app.core.control.policies.baseline import BaselineController
from infra.data.traffic_adapters import snapshot_from_legacy
from test.fixtures.v2_baseline_controller import (
    FIXTURE, SELECTOR_CASES, compact_round, config_sources, full_replay,
    global_control, green_wave, isolated_runtime, selector_replay,
    sensor_request, shadow, shadow_summary,
)


class BaselineControllerRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_frozen_configuration_sources_match_the_reviewed_baseline(self):
        self.assertEqual(config_sources(), self.golden["config_sources"])

    def test_real_selector_modes_and_single_candidate_preserve_legacy_results(self):
        controller = BaselineController()
        self.assertEqual(selector_replay(), self.golden["selectors"])
        self.assertEqual(selector_replay(controller.select_legacy), self.golden["selectors"])
        for name, cross_id, mode in SELECTOR_CASES:
            with self.subTest(case=name), isolated_runtime(
                mode=mode, fallback=name == "pilot_fallback",
            ) as directory:
                with patch.object(shadow.LOGGER, "exception"):
                    candidate = controller.predict(snapshot_from_legacy(sensor_request(cross_id, observed=True)))
                expected = self.golden["selectors"][name]
                self.assertEqual(candidate.intersection_id, cross_id)
                self.assertEqual(signal_plan_to_legacy(candidate), expected["legacy_result"][0])
                self.assertEqual(shadow_summary(directory), expected["shadow"])

        pilot = self.golden["selectors"]["pilot_new"]
        legacy = self.golden["selectors"]["old_experience"]
        fallback = self.golden["selectors"]["pilot_fallback"]
        self.assertEqual(pilot["shadow"][0]["selected_schedule_source"], "new")
        self.assertTrue(pilot["shadow"][0]["quality_passed"])
        self.assertNotEqual(pilot["legacy_result"][0], legacy["legacy_result"][0])
        self.assertEqual(fallback["legacy_result"], legacy["legacy_result"])
        self.assertEqual(fallback["shadow"][0]["selection_fallback_reason"], "new_evaluation_error")

    def test_two_complete_rounds_preserve_plans_reports_payloads_and_tcp_bytes(self):
        controller = BaselineController()
        legacy = full_replay()
        wrapped = full_replay(controller.select_legacy, controller.coordinate_legacy)
        self.assertEqual(wrapped, legacy)
        for index, (actual, expected) in enumerate(zip(wrapped, self.golden["rounds"])):
            with self.subTest(round=index):
                self.assertEqual(compact_round(actual), expected)
                self.assertEqual(len(actual["after_phase_check"]), 186)
                self.assertEqual(len(actual["tcp_frames"]), 186)
                self.assertTrue(all(frame.endswith(b"\n") for frame in actual["tcp_frames"]))
                self.assertTrue(all(type(value) is int for plan in actual["after_coordinate"].values()
                                    for value in plan))
                self.assertTrue(actual["phase_report"]["1300068"]["modifications"])
                self.assertEqual(actual["green_wave_state"]["lvbo_01"]["cnt"], index + 1)
        # The special road copies the mixed plan before phase_check; its
        # missing configuration intentionally leaves that copied plan unclipped.
        self.assertEqual(wrapped[0]["after_coordinate"]["2719089"],
                         wrapped[0]["after_coordinate"]["1300068"])
        self.assertNotEqual(wrapped[0]["after_phase_check"]["2719089"],
                            wrapped[0]["after_phase_check"]["1300068"])
        self.assertEqual(wrapped[0]["after_phase_check"]["1300782"], [0] * 10)

    def test_replay_restores_shared_state_and_random_generator(self):
        internet_object = global_control.inter_road_state
        internet_before = copy.deepcopy(internet_object)
        green_before = {
            name: copy.deepcopy(value) for name, value in vars(green_wave).items()
            if not name.startswith("__")
            and isinstance(value, (dict, list, set, str, bool, int, float, type(None)))
        }
        random_before = random.getstate()
        full_replay()
        self.assertIs(global_control.inter_road_state, internet_object)
        self.assertEqual(global_control.inter_road_state, internet_before)
        for name, value in green_before.items():
            self.assertEqual(getattr(green_wave, name), value, name)
        self.assertEqual(random.getstate(), random_before)


if __name__ == "__main__":
    unittest.main()
