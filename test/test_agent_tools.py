"""Agent 数据查询工具契约测试。"""

from __future__ import annotations

import unittest

from agent.tools import DataQueryTools


class _QueryServiceStub:
    def get_runtime_data(self, kind, limit):
        return [{"kind": kind, "limit": limit}]

    def get_runtime_history(self, kind, **kwargs):
        return [{"kind": kind, **kwargs}]

    def get_latest_results(self):
        return [{"cross_id": "1300068"}, {"cross_id": "1300106"}]

    def get_config_snapshot(self, resource, cross_id=None):
        return {"resource": resource, "cross_id": cross_id}

    def get_experience(self, key=None, category=None):
        if key:
            return {"strategy": "extend_green"}
        return [
            {
                "key": "morning_peak",
                "category": category or "signal",
                "value": {"strategy": "extend_green"},
                "updated_at": "2026-08-06T00:00:00+00:00",
            }
        ]


class DataQueryToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = DataQueryTools(_QueryServiceStub())

    def test_runtime_history_contract(self) -> None:
        result = self.tools.invoke(
            "query_runtime_history",
            {
                "kind": "flow",
                "intersection_id": "1300068",
                "limit": 10,
                "detail": "full",
            },
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["meta"]["source"], "runtime_repository")
        self.assertEqual(result["data"][0]["intersection_id"], "1300068")

    def test_summary_mode_hides_raw_payload(self) -> None:
        result = self.tools.query_recent_runtime_data("flow")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["count"], 1)
        self.assertIn("fields", result["data"]["items"][0])
        self.assertEqual(result["meta"]["detail"], "summary")

    def test_tool_errors_and_limits_are_structured(self) -> None:
        unknown = self.tools.invoke("unknown_tool")
        invalid_limit = self.tools.query_latest_results(limit=101)
        self.assertEqual(unknown["status"], "error")
        self.assertEqual(invalid_limit["status"], "error")

    def test_tool_schemas_are_exposed(self) -> None:
        names = {item["name"] for item in self.tools.tool_schemas()}
        self.assertIn("query_recent_runtime_data", names)
        self.assertIn("query_config_snapshot", names)
        self.assertIn("query_experience_pool", names)

    def test_experience_pool_tool_contract(self) -> None:
        result = self.tools.invoke(
            "query_experience_pool",
            {"category": "signal", "detail": "summary"},
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["meta"]["source"], "experience_pool")
        self.assertEqual(result["data"]["items"][0]["key"], "morning_peak")


if __name__ == "__main__":
    unittest.main()
