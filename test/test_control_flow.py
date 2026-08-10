"""分步放行控制流程的规则函数测试。"""

import unittest

from app.core.tools.control_flow import (
    CONTROL_STEPS,
    build_initial_context,
    query_data_hub_summary,
)


def run_all_steps(cross_id: str = "12345"):
    """按流程顺序执行全部步骤，返回 {key: data}。"""
    context = build_initial_context(cross_id)
    data = {}
    for item in CONTROL_STEPS:
        data[item["key"]] = item["fn"](context)
    return data, context


class ControlFlowRulesTest(unittest.TestCase):
    def test_all_steps_run_and_ten_steps(self):
        data, _ = run_all_steps()
        self.assertEqual(len(CONTROL_STEPS), 10)
        for item in CONTROL_STEPS:
            self.assertIn(item["key"], data)

    def test_input_summary_contains_cross_id_and_constraints(self):
        data, _ = run_all_steps("1300068")
        summary = data["task_summary"]
        self.assertEqual(summary["intersection_id"], "1300068")
        self.assertEqual(summary["time_window"], "past_10_minutes")
        self.assertIn("traffic_state", summary)
        self.assertIn("signal_constraints", summary)

    def test_anomaly_detect_flags_east_west_through(self):
        data, _ = run_all_steps()
        anomaly = data["anomaly_detect"]
        self.assertTrue(anomaly["abnormal"])
        self.assertEqual(anomaly["severity"], "high")
        self.assertEqual(anomaly["affected_movements"], ["东西直行"])

    def test_anomaly_handle_prioritizes_worst_direction(self):
        data, _ = run_all_steps()
        handling = data["anomaly_handle"]
        self.assertEqual(handling["priority_movements"], ["东西直行"])
        self.assertIn("strategy", handling)

    def test_weights_sum_to_one(self):
        data, _ = run_all_steps()
        for key in ("single_point_weight", "global_weight", "fuse_weight"):
            weights = data[key].get("single_point_weight") or data[key].get("global_weight") or data[key].get("fused_weight")
            self.assertAlmostEqual(sum(weights.values()), 1.0, places=2)

    def test_signal_plan_keeps_cycle_and_green_sum(self):
        data, _ = run_all_steps()
        plan = data["to_signal_plan"]
        self.assertEqual(plan["cycle"], 120)
        self.assertEqual(len(plan["phases"]), 4)
        total_green = sum(p["green"] for p in plan["phases"])
        self.assertEqual(total_green, plan["available_green"])
        self.assertEqual(plan["available_green"], 100)

    def test_safety_check_finds_pedestrian_issue_and_repair_fixes_it(self):
        data, _ = run_all_steps()
        safety = data["safety_check"]
        self.assertFalse(safety["safe"])
        issues = {i["type"] for i in safety["issues"]}
        self.assertIn("pedestrian_green_insufficient", issues)

        repaired = data["repair"]["repaired_signal_plan"]
        repaired_by_id = {p["phase_id"]: p for p in repaired["phases"]}
        p3 = repaired_by_id["P3"]
        self.assertGreaterEqual(p3["green"], 28)
        # 修正后周期与绿灯总和保持不变
        self.assertEqual(sum(p["green"] for p in repaired["phases"]), 100)

    def test_finalize_returns_dispatchable_plan(self):
        data, _ = run_all_steps()
        final_plan = data["finalize"]["final_control_plan"]
        self.assertEqual(final_plan["intersection_id"], "12345")
        self.assertTrue(final_plan["dispatch_decision"]["allow_dispatch"])
        self.assertEqual(len(final_plan["phases"]), 4)

    def test_query_data_hub_summary_returns_none_without_service(self):
        self.assertIsNone(query_data_hub_summary("12345", None))

    def test_query_data_hub_summary_uses_real_records(self):
        class FakeQuery:
            def get_runtime_data(self, kind, limit=None):
                if kind == "flow":
                    return [
                        {"intersection_id": "1300068", "payload": {"count": 8}},
                        {"intersection_id": "1300068", "payload": {"count": 12}},
                        {"intersection_id": "999", "payload": {"count": 100}},
                    ]
                return []

        summary = query_data_hub_summary("1300068", FakeQuery())
        self.assertEqual(summary["flow_records"], 2)
        self.assertEqual(summary["avg_flow_count"], 10.0)


if __name__ == "__main__":
    unittest.main()
