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
            },
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["meta"]["source"], "runtime_repository")
        self.assertEqual(result["data"][0]["intersection_id"], "1300068")

    def test_tool_errors_and_limits_are_structured(self) -> None:
        unknown = self.tools.invoke("unknown_tool")
        invalid_limit = self.tools.query_latest_results(limit=101)
        self.assertEqual(unknown["status"], "error")
        self.assertEqual(invalid_limit["status"], "error")

    def test_tool_schemas_are_exposed(self) -> None:
        names = {item["name"] for item in self.tools.tool_schemas()}
        self.assertIn("query_recent_runtime_data", names)
        self.assertIn("query_config_snapshot", names)


if __name__ == "__main__":
    unittest.main()
