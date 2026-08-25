"""MCP 服务器（方向A）测试：统一注册中心 + stdio 客户端联通验证。"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

from agent.mcp_server import build_unified_registry

#: 数据查询工具 + 信号控制工具的全部工具名。
EXPECTED_TOOLS = [
    "query_recent_runtime_data",
    "query_runtime_history",
    "query_latest_results",
    "query_config_snapshot",
    "query_config_pool",
    "query_experience_pool",
    "generate_single_intersection_signal_timing",
    "generate_intersection_plan",
    "get_timetable_plan",
    "process_all_intersections",
]


class TestBuildUnifiedRegistry(unittest.TestCase):
    """统一注册中心装配测试。"""

    def test_registry_contains_all_tools(self) -> None:
        registry = build_unified_registry()
        names = registry.names()
        for expected in EXPECTED_TOOLS:
            self.assertIn(expected, names)
        self.assertEqual(len(names), len(EXPECTED_TOOLS))

    def test_invoke_lightweight_tool(self) -> None:
        """直接调用一个无必填参数的工具。"""
        registry = build_unified_registry()
        result = registry.invoke("query_latest_results", {"limit": 3})
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        self.assertEqual(result["status"], "ok")

    def test_schemas_valid(self) -> None:
        """每个工具都带合法的 JSON Schema 参数定义。"""
        registry = build_unified_registry()
        for spec in registry.all_specs():
            self.assertEqual(spec.parameters.get("type"), "object")
            self.assertIsInstance(spec.parameters.get("properties"), dict)


class TestMcpServerOverStdio(unittest.TestCase):
    """通过 stdio 客户端真实启动子进程验证 list_tools / call_tool。"""

    def test_list_and_call_tools(self) -> None:
        async def run() -> None:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=PYTHON,
                args=[str(ROOT / "agent" / "mcp_server.py")],
                cwd=str(ROOT),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = [tool.name for tool in tools.tools]
                    for expected in EXPECTED_TOOLS:
                        self.assertIn(expected, names)

                    # 调用一个无必填参数的工具，验证链路
                    result = await session.call_tool("query_latest_results", {"limit": 3})
                    self.assertIsNotNone(result)
                    text = "".join(
                        c.text for c in result.content if getattr(c, "type", "") == "text"
                    )
                    self.assertIn("最新决策结果", text)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
