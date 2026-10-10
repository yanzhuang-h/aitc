"""最终安全门：结构、真实规则、修正、fallback 与配置快照隔离。"""

import copy
import logging
import math
import unittest
from unittest.mock import Mock

from app.core.control.adapters import signal_plan_from_legacy
from app.core.control.safety_engine import ControlSafetyEngine
from phase_check import phase_check


ROAD = "100"
PLAN = [25, 30, 0, 0, 0, 0, 0, 0, 0, 1]
CONFIG = {ROAD: {"1": {"0": [20, 40], "1": [25, 45]}}}


def engine(config=None, **kwargs):
    return ControlSafetyEngine(
        config_supplier=lambda: copy.deepcopy(CONFIG if config is None else config),
        phase_check=phase_check, logger=Mock(spec=logging.Logger), **kwargs,
    )


class SafetyEngineTest(unittest.TestCase):
    def test_strict_valid_plan_preserves_float_durations_and_program_representation(self):
        for program in (1, 1.0, "1", "01"):
            plan = list(PLAN)
            plan[0], plan[9] = 25.5, program
            result = engine().check(ROAD, plan)
            self.assertEqual(result.status, "valid")
            self.assertTrue(result.safe)
            self.assertEqual(result.plan.phase_times[0], 25.5)
            self.assertEqual(result.plan.program_id, program)

    def test_contract_rejects_lengths_booleans_strings_negative_and_nonfinite_times(self):
        bad = [None, {}, "plan", PLAN[:9], PLAN + [0]]
        for value in (True, "25", -1, math.inf, math.nan):
            plan = list(PLAN)
            plan[0] = value
            bad.append(plan)
        for plan in bad:
            with self.subTest(plan=plan):
                self.assertEqual(engine().check(ROAD, plan).status, "invalid")

    def test_program_id_does_not_silently_truncate_or_coerce(self):
        for program in (-1, 1.5, "1.0", "x", "-1", " 1", True, math.nan, math.inf):
            with self.subTest(program=program):
                plan = list(PLAN)
                plan[9] = program
                self.assertEqual(engine().check(ROAD, plan).status, "invalid")

    def test_hidden_phase_after_first_zero_is_rejected(self):
        plan = list(PLAN)
        plan[3] = 20
        result = engine().check(ROAD, plan)
        self.assertEqual(result.status, "invalid")
        self.assertIn("phase_3_after_zero_terminator", result.issues)

    def test_reserved_slot_cannot_leak_into_phase_payload(self):
        for value in (-1, 9, math.inf, True):
            plan = [20] * 8 + [value, 1]
            with self.subTest(value=value):
                self.assertEqual(engine().check(ROAD, plan).status, "invalid")
        config = {ROAD: {"1": {str(n): [10, 40] for n in range(8)}}}
        self.assertEqual(engine(config).check(ROAD, [20] * 8 + [0, 1]).status, "valid")

    def test_zero_plan_is_existing_no_action_marker_not_a_safe_timing_plan(self):
        result = engine().check(ROAD, [0] * 10)
        self.assertEqual(result.status, "no_action")
        self.assertIsNone(result.safe)
        self.assertEqual(engine().check(ROAD, [0] * 9 + [1]).status, "invalid")

    def test_missing_road_program_or_phase_rules_are_explicit_partial_coverage(self):
        for config, expected in (({}, "intersection_config"),
                                 ({ROAD: {"2": CONFIG[ROAD]["1"]}}, "program_config"),
                                 ({ROAD: {"1": {"0": [20, 40]}}}, "phase_1_bounds")):
            with self.subTest(config=config):
                gate = engine(config)
                result = gate.check(ROAD, PLAN)
                self.assertEqual(result.status, "partial")
                self.assertIsNone(result.safe)
                self.assertIn(expected, result.missing_rules)
                final, reports = gate.finalize({ROAD: PLAN})
                self.assertEqual(final[ROAD], PLAN)
                self.assertEqual(reports[ROAD]["safety_status"], "partial")
                self.assertIsNone(reports[ROAD]["safe"])
                gate.logger.warning.assert_called_once()

    def test_absent_required_configured_phase_triggers_fallback(self):
        plan = list(PLAN)
        plan[1] = 0
        final, reports = engine().finalize({ROAD: plan}, fallback_plans={ROAD: PLAN})
        self.assertEqual(final[ROAD], PLAN)
        self.assertEqual(reports[ROAD]["fallback_source"], "baseline_candidate")
        self.assertIn("phase_1_required_by_config", reports[ROAD]["fallback_reason"])

    def test_known_boundaries_preserve_old_phase_check_repairs(self):
        plan = list(PLAN)
        plan[0], plan[1] = 2.5, 80.5
        before = copy.deepcopy(plan)
        self.assertEqual(engine().check(ROAD, plan).status, "invalid")
        final, reports = engine().finalize({ROAD: plan})
        expected, report = phase_check({ROAD: copy.deepcopy(plan)}, config_snapshot=CONFIG)
        self.assertEqual(final, expected)
        self.assertEqual(reports[ROAD]["modifications"], report[ROAD]["modifications"])
        self.assertEqual(reports[ROAD]["safety_status"], "valid")
        self.assertIsNone(reports[ROAD]["fallback_source"])
        self.assertEqual(plan, before)

    def test_clamp_that_creates_hidden_phase_cannot_pass(self):
        config = {ROAD: {"1": {"0": [0, 0], "1": [25, 45]}}}
        final, reports = engine(config).finalize({ROAD: PLAN})
        self.assertEqual(final[ROAD], [0] * 10)
        self.assertEqual(reports[ROAD]["fallback_source"], "no_action")
        self.assertIn("phase_1_after_zero_terminator", reports[ROAD]["fallback_reason"])

    def test_invalid_static_rules_do_not_masquerade_as_missing_rules(self):
        for rules in ([], {}, {"0": [-1, 30]}, {"0": [40, 20]}, {"0": [True, 40]},
                      {"0": [20, math.inf]}, {"0": ["20", 40]}, {"9": [20, 40]}, {"0": [20]}):
            with self.subTest(rules=rules):
                gate = engine({ROAD: {"1": rules}})
                result = gate.check(ROAD, PLAN)
                self.assertEqual(result.status, "invalid")
                self.assertEqual(result.issues, ["invalid_static_config"])
                final, report = gate.finalize({ROAD: PLAN})
                self.assertEqual(final[ROAD], [0] * 10)
                self.assertEqual(report[ROAD]["fallback_source"], "no_action")

    def test_fallback_candidate_is_revalidated_with_current_bounds(self):
        candidate = list(PLAN)
        candidate[0] = 5
        loader = Mock(side_effect=AssertionError("candidate is recoverable"))
        gate = engine(fallback_loader=loader)
        final, reports = gate.finalize({ROAD: None}, fallback_plans={ROAD: candidate})
        self.assertEqual(final[ROAD][0], 20)
        self.assertEqual(reports[ROAD]["fallback_source"], "baseline_candidate")
        self.assertTrue(reports[ROAD]["safe"])
        loader.assert_not_called()

    def test_timetable_is_loaded_once_only_after_candidate_fails(self):
        loader = Mock(return_value=PLAN)
        final, reports = engine(fallback_loader=loader).finalize({ROAD: None})
        self.assertEqual(final[ROAD], PLAN)
        self.assertEqual(reports[ROAD]["fallback_source"], "timetable")
        loader.assert_called_once()
        self.assertEqual(loader.call_args.args[0], ROAD)
        self.assertIsInstance(loader.call_args.args[1], float)

    def test_partial_fallback_is_retained_with_unknown_safety(self):
        final, reports = engine({}, fallback_loader=Mock(return_value=PLAN)).finalize(
            {ROAD: None}, fallback_plans={ROAD: PLAN},
        )
        self.assertEqual(final[ROAD], PLAN)
        self.assertEqual(reports[ROAD]["safety_status"], "partial")
        self.assertEqual(reports[ROAD]["fallback_source"], "baseline_candidate")
        self.assertIsNone(reports[ROAD]["safe"])

    def test_invalid_fallback_is_not_accepted(self):
        for fallback in (None, [20, 0, 30] + [0] * 7):
            with self.subTest(fallback=fallback):
                final, reports = engine(CONFIG, fallback_loader=Mock(return_value=fallback)).finalize(
                    {ROAD: None}, fallback_plans={ROAD: fallback},
                )
                self.assertEqual(final[ROAD], [0] * 10)
                self.assertEqual(reports[ROAD]["safety_status"], "no_action")
                self.assertIsNone(reports[ROAD]["safe"])

    def test_one_invalid_road_does_not_change_another_road(self):
        config = dict(CONFIG, **{"200": CONFIG[ROAD]})
        final, reports = engine(config).finalize({ROAD: PLAN, "200": None})
        self.assertEqual(final[ROAD], PLAN)
        self.assertEqual(final["200"], [0] * 10)
        self.assertIsNone(reports[ROAD]["fallback_source"])

    def test_snapshot_is_fixed_across_check_repair_and_all_roads(self):
        config = dict(CONFIG, **{"200": CONFIG[ROAD]})
        supplier = Mock(return_value=config)
        seen = []

        def checker(plans, *, config_snapshot):
            seen.append(copy.deepcopy(config_snapshot))
            config[ROAD] = {"1": {"0": [100, 120]}}
            return phase_check(plans, config_snapshot=config_snapshot)

        gate = ControlSafetyEngine(config_supplier=supplier, phase_check=checker)
        final, reports = gate.finalize({ROAD: PLAN, "200": PLAN})
        supplier.assert_called_once()
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(final, {ROAD: PLAN, "200": PLAN})
        self.assertTrue(all(r["safe"] for r in reports.values()))

    def test_inputs_and_returned_models_do_not_share_mutable_data(self):
        config, plans = copy.deepcopy(CONFIG), {ROAD: list(PLAN)}
        before = copy.deepcopy((config, plans))
        gate = engine(config)
        final, report = gate.finalize(plans)
        final[ROAD][0] = 999
        report[ROAD]["issues"].append("external mutation")
        self.assertEqual((config, plans), before)
        model = signal_plan_from_legacy(ROAD, PLAN)
        self.assertEqual(model.phase_times[0], 25)

    def test_programming_or_loader_errors_propagate(self):
        gate = engine(fallback_loader=Mock(side_effect=RuntimeError("broken fallback implementation")))
        with self.assertRaisesRegex(RuntimeError, "broken fallback"):
            gate.finalize({ROAD: None})


if __name__ == "__main__":
    unittest.main()
