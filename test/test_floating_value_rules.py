import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import phase_check
from lib import floating_value
from lib.nacos_config_sync import NacosConfigSync


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

    def seed_existing_record(self):
        existing = dict(self.payload, phase_offsets=[0, 0, 0])
        self.path.write_text(json.dumps([existing]), encoding="utf-8")
        return self.path.read_bytes()

    def test_unknown_road_or_plan_is_rejected_without_creating_file_changes(self):
        before = self.seed_existing_record()
        for key, value in [("Cross_id", "unknown"), ("Change_id", "0")]:
            with self.subTest(key=key):
                payload = dict(self.payload, **{key: value})
                result = floating_value.update_floating_value(
                    payload, path=str(self.path),
                )
                self.assertFalse(result["saved"])
                self.assertEqual(result["status"], "error")
                self.assertEqual(self.path.read_bytes(), before)

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

    def test_invalid_batch_reports_each_record_and_keeps_previous_file(self):
        before = self.seed_existing_record()
        plan = self.road_info["1700240"]["1"]
        self.road_info["2706149"] = {"1": plan}
        self.road_info["2703320"] = {"1": plan, "2": plan}
        records = [
            self.payload,
            dict(self.payload, Cross_id="2706149", Change_id="0"),
            {"Cross_id": "2706149"},
            dict(self.payload, Cross_id="2703320", Change_id="0"),
        ]
        with self.assertRaises(ValueError) as captured:
            floating_value.replace_floating_value_records(records, path=str(self.path))
        reason = str(captured.exception)
        self.assertIn("index 1: No phase rules for Cross_id 2706149, Change_id 0", reason)
        self.assertIn("configured Change_id values: 1)", reason)
        self.assertIn("index 2: missing required payload field: Change_id", reason)
        self.assertIn("index 3: No phase rules for Cross_id 2703320, Change_id 0", reason)
        self.assertIn("configured Change_id values: 1, 2)", reason)
        self.assertEqual(self.path.read_bytes(), before)

    def test_round_normalizes_each_rule_once_and_preserves_last_matching_range(self):
        records = [
            self.payload,
            dict(self.payload, time_during_start="17:20", phase_offsets=[10]),
            dict(self.payload, Change_id="2", phase_offsets=[99]),
            dict(self.payload, IS_work_day="no", phase_offsets=[99]),
            dict(self.payload, Cross_id="2706149", phase_offsets=[-20, 10]),
            {"Cross_id": "1700240"},
        ]
        self.path.write_text(json.dumps(records), encoding="utf-8")
        action = [50, 50, 50] + [0] * 6 + [1]
        actions = {"1700240": action, "2706149": action, "2703320": action}
        with (
            mock.patch.object(floating_value, "_workday_key", return_value="yes"),
            mock.patch.object(floating_value, "_time_slot_key", return_value="17:30"),
            mock.patch.object(floating_value, "_normalize_floating_update_payload",
                              wraps=floating_value._normalize_floating_update_payload) as normalize,
            self.assertLogs("lib.floating_value", level="INFO") as logs,
        ):
            adjusted, report = floating_value.apply_floating_value(
                actions, current_time=0, path=str(self.path), return_report=True,
            )
        self.assertEqual(normalize.call_count, len(records))
        self.assertEqual(adjusted["1700240"][:3], [60, 50, 50])
        self.assertEqual(adjusted["2706149"][:3], [30, 60, 50])
        self.assertEqual(adjusted["2703320"], action)
        self.assertEqual(action[:3], [50, 50, 50])
        self.assertEqual([change["intersection_id"] for change in report["modifications"]],
                         ["1700240", "2706149"])
        self.assertIn("matches={'road': 4, 'day': 3, 'program': 2, 'time': 2}",
                      next(line for line in logs.output if "cross_id=1700240" in line))

    def test_nacos_repeats_same_error_periodically_and_recovers_when_plan_is_fixed(self):
        before = self.seed_existing_record()
        payload = dict(self.payload, Change_id="0")
        sync = NacosConfigSync(path=str(self.path))
        sync.password = "test"
        poll_count = 0

        def wait(_interval):
            nonlocal poll_count
            poll_count += 1
            if poll_count == 3:
                self.assertEqual(self.path.read_bytes(), before)
                self.road_info["1700240"]["0"] = self.road_info["1700240"]["1"]
            elif poll_count == 4:
                sync._stop_event.set()

        with (
            mock.patch.object(sync, "_get_config", return_value={"content": json.dumps([payload])}) as load,
            mock.patch.object(sync._stop_event, "wait", side_effect=wait),
            mock.patch("lib.nacos_config_sync.monotonic", side_effect=[100, 105, 400]),
            self.assertLogs("lib.nacos_config_sync", level="INFO") as captured,
        ):
            sync._run()

        self.assertEqual(load.call_count, 4)
        errors = [record for record in captured.records if record.levelname == "ERROR"]
        self.assertEqual(len(errors), 2)
        self.assertIn("Change_id 0", errors[0].getMessage())
        self.assertIn("sync recovered", captured.output[-1])
        self.assertEqual(json.loads(self.path.read_text()), [payload])

    def test_malformed_road_info_is_rejected_without_replacing_existing_records(self):
        before = self.seed_existing_record()
        for field, value in [
            ("phase", 1),
            ("min_pass_time", ["invalid", 20, 35]),
            ("max_pass_time", [None, 200, 200]),
        ]:
            with self.subTest(field=field):
                original = self.road_info["1700240"]["1"][field]
                self.road_info["1700240"]["1"][field] = value
                try:
                    result = self.validate()
                    self.assertEqual(result["status"], "invalid")
                    self.assertIn("Invalid road_info rules", result["reason"])
                    with self.assertRaisesRegex(ValueError, "Invalid road_info rules"):
                        floating_value.replace_floating_value_records(
                            [self.payload], path=str(self.path),
                        )
                    self.assertEqual(self.path.read_bytes(), before)
                finally:
                    self.road_info["1700240"]["1"][field] = original

    def test_final_phase_bounds_still_limit_adjusted_green(self):
        action = [190, 50, 50] + [0] * 6 + [1]
        adjusted = floating_value._apply_phase_offsets(action, [20, 0, 0])
        phase_check.phase_check(
            {"1700240": adjusted}, config_snapshot=self.phase_rules,
        )
        self.assertEqual(adjusted, [200, 50, 50] + [0] * 6 + [1])


if __name__ == "__main__":
    unittest.main()
