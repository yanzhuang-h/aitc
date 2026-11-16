import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import phase_check
from lib import floating_value


class FloatingValueRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "floating_value.json"
        self.path.write_text("[]", encoding="utf-8")
        patcher = mock.patch.object(floating_value, "_cache_mtime", None)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(floating_value, "_cache_data", [])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.phase_rules = {}
        self.road_info = {
            "1700240": {
                "1": {
                    "phase": ["UD", "UDL", "LR"],
                    "min_pass_time": [20, 20, 35],
                    "max_pass_time": [200, 200, 200],
                }
            }
        }
        self.payload = {
            "Cross_id": "1700240",
            "Change_id": "1",
            "IS_work_day": "yes",
            "time_during_start": "09:00",
            "time_during_end": "17:30",
            "phase_offsets": [20, 0, 0],
        }
        patcher = mock.patch.object(
            floating_value, "_get_phase_rule_config",
            side_effect=lambda: (self.phase_rules, None),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            phase_check, "_load_road_info_config", return_value=self.road_info,
        )
        self.road_loader = patcher.start()
        self.addCleanup(patcher.stop)

    def validate(self, payload=None):
        return floating_value.validate_floating_value_update(
            self.payload if payload is None else payload, path=str(self.path),
        )

    def test_road_info_allows_manual_adjustment_without_explicit_rules(self):
        result = self.validate()
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["rule_check"]["plan_rules"]["0"], [20, 200])

        floating_value.replace_floating_value_records(
            [self.payload], path=str(self.path),
        )
        self.assertEqual(json.loads(self.path.read_text()), [self.payload])
        action = [50, 50, 50] + [0] * 6 + [1]
        with mock.patch.object(floating_value, "_workday_key", return_value="yes"), \
                mock.patch.object(floating_value, "_time_slot_key", return_value="14:50"):
            adjusted = floating_value.apply_floating_value(
                {"1700240": action}, current_time=0, path=str(self.path),
            )["1700240"]
        self.assertEqual(adjusted, [70, 50, 50] + [0] * 6 + [1])
        self.assertEqual(action, [50, 50, 50] + [0] * 6 + [1])
        phase_check.phase_check(
            {"1700240": adjusted}, config_snapshot=self.phase_rules,
        )
        self.assertEqual(adjusted, [70, 50, 50] + [0] * 6 + [1])

    def test_explicit_plan_rules_take_priority(self):
        self.phase_rules["1700240"] = {"1": {"0": [40, 50]}}
        result = self.validate()
        self.assertEqual(result["status"], "invalid")
        self.assertIn("exceeds allowed rule width 10", result["reason"])
        self.road_loader.assert_not_called()

    def test_missing_explicit_plan_uses_matching_road_info_plan(self):
        self.phase_rules["1700240"] = {"0": {"0": [40, 50]}}
        self.assertEqual(self.validate()["status"], "valid")

    def test_unknown_road_or_plan_is_rejected_without_creating_file_changes(self):
        for key, value in [("Cross_id", "unknown"), ("Change_id", "0")]:
            with self.subTest(key=key):
                payload = dict(self.payload, **{key: value})
                result = floating_value.update_floating_value(
                    payload, path=str(self.path),
                )
                self.assertFalse(result["saved"])
                self.assertEqual(result["status"], "error")
                self.assertEqual(self.path.read_text(), "[]")

    def test_nonexistent_phase_and_excessive_offset_remain_invalid(self):
        for offsets, reason in [
            ([0, 0, 0, 20], "has no rule for this phase"),
            ([181, 0, 0], "exceeds allowed rule width 180"),
            ([-181, 0, 0], "exceeds allowed rule width 180"),
        ]:
            with self.subTest(offsets=offsets):
                result = self.validate(dict(self.payload, phase_offsets=offsets))
                self.assertEqual(result["status"], "invalid")
                self.assertIn(reason, result["reason"])

    def test_invalid_record_keeps_previous_file_unchanged(self):
        before = self.path.read_bytes()
        invalid = copy.deepcopy(self.payload)
        invalid["Change_id"] = "0"
        with self.assertRaisesRegex(ValueError, "record at index 1"):
            floating_value.replace_floating_value_records(
                [self.payload, invalid], path=str(self.path),
            )
        self.assertEqual(self.path.read_bytes(), before)

    def test_final_phase_bounds_still_limit_adjusted_green(self):
        action = [190, 50, 50] + [0] * 6 + [1]
        adjusted = floating_value._apply_phase_offsets(action, [20, 0, 0])
        phase_check.phase_check(
            {"1700240": adjusted}, config_snapshot=self.phase_rules,
        )
        self.assertEqual(adjusted, [200, 50, 50] + [0] * 6 + [1])


if __name__ == "__main__":
    unittest.main()
