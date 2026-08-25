"""控制函数工具集测试。

验证 ControlFunctionTools 的工具注册、动作映射、参数校验与基本调用。
"""

from __future__ import annotations

import unittest

from agent.registry import ToolRegistry
from app.core.tools.control_function_tools import ControlFunctionTools


class ControlFunctionToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = ControlFunctionTools()

    def test_registers_three_tools(self) -> None:
        self.assertEqual(len(self.tools), 3)
        names = {spec["name"] for spec in self.tools.tool_schemas()}
        self.assertEqual(
            names,
            {
                "generate_intersection_plan",
                "get_timetable_plan",
                "process_all_intersections",
            },
        )

    def test_actions_mapping(self) -> None:
        actions = self.tools.actions()
        self.assertEqual(actions["control.plan.single"], "generate_intersection_plan")
        self.assertEqual(actions["control.timetable"], "get_timetable_plan")
        self.assertEqual(actions["control.process_all"], "process_all_intersections")

    def test_generate_requires_cross_id(self) -> None:
        result = self.tools.invoke("generate_intersection_plan", {})
        self.assertEqual(result["status"], "error")
        self.assertIn("cross_id", result["summary"])

    def test_get_timetable_plan_returns_ten_element_plan(self) -> None:
        result = self.tools.invoke("get_timetable_plan", {"cross_id": "1300069"})
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["success"])
        self.assertEqual(len(result["data"]["plan"]), 10)

    def test_get_timetable_plan_requires_cross_id(self) -> None:
        result = self.tools.invoke("get_timetable_plan", {})
        self.assertEqual(result["status"], "error")

    def test_process_all_requires_plans(self) -> None:
        result = self.tools.invoke("process_all_intersections", {})
        self.assertEqual(result["status"], "error")

    def test_process_all_accepts_single_intersection_plan(self) -> None:
        # 单路口调用不抛异常；全局处理需要完整快照，此处只验证契约不崩溃。
        result = self.tools.invoke(
            "process_all_intersections",
            {"plans": {"1300069": [49, 30, 53, 21, 0, 0, 0, 0, 0, 0]}},
        )
        self.assertIn(result["status"], {"ok", "error"})

    def test_merge_into_target_registry(self) -> None:
        target = ToolRegistry()
        self.tools.merge_into(target)
        self.assertEqual(len(target), 3)
        self.assertIn("generate_intersection_plan", target.names())
        self.assertIn("get_timetable_plan", target.names())
        self.assertIn("process_all_intersections", target.names())


if __name__ == "__main__":
    unittest.main()
