"""符号主义 Agent 与数据底座完整链路测试。"""

from __future__ import annotations

import tempfile
import unittest

from agent.qwen_agent import QwenSignalTimingAgent, SymbolicDataAgent
from agent.tools import DataQueryTools
from app.core.tools import SingleIntersectionSignalTimingTool
from infra.data import (
    ConfigService,
    DataKind,
    LongTermMemory,
    ResultWarehouse,
    ShortTermMemory,
    MemoryQueryLayer,
    RuntimeDataReceiver,
)


class _MemoryWriter:
    def write(self, kind, data) -> None:
        pass


class _Lambdas:
    location_to_intersection_lambda = {1: ("1300068", "U")}


class _ChatResult:
    def __init__(self, content):
        self.content = content


class _LLMClient:
    model = "fake-qwen"

    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if len(self.calls) == 1:
            return _ChatResult('{"action":"signal.timing.single","arguments":{"cross_id":"1300068"}}')
        return _ChatResult("路口 1300068 的放行方案已生成。")


class SymbolicDataAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        repository = LongTermMemory(root=self.tempdir.name)
        cache = ShortTermMemory({DataKind.FLOW: 60})
        receiver = RuntimeDataReceiver(
            cache=cache,
            writer=_MemoryWriter(),
            repository=repository,
            lambdas_module=_Lambdas(),
        )
        receiver.receive_tcp({"ycsb_xsfx": "U", "jtll_ddbh": "1", "count": 8})

        results = ResultWarehouse()
        results.replace([{"Cross_id": "1300068", "result_action": [1, 2, 3]}])
        query_service = MemoryQueryLayer(
            short_term_memory=cache,
            result_warehouse=results,
            config_service=ConfigService(),
            long_term_memory=repository,
        )
        self.agent = SymbolicDataAgent(DataQueryTools(query_service))

        def fake_dqn_select(*args):
            return [10, 20], {"Start1": 1}, {"model": "fake"}, {"exp": "ok"}

        signal_tool = SingleIntersectionSignalTimingTool(dqn_select=fake_dqn_select)
        self.agent_with_signal_tool = SymbolicDataAgent(
            DataQueryTools(query_service, signal_timing_tool=signal_tool)
        )
        self.qwen_agent = QwenSignalTimingAgent(
            _LLMClient(),
            DataQueryTools(query_service, signal_timing_tool=signal_tool),
        )

    def test_full_history_query_flow(self) -> None:
        result = self.agent.run(
            {
                "action": "runtime.history",
                "arguments": {
                    "kind": "flow",
                    "intersection_id": "1300068",
                    "detail": "full",
                },
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["meta"]["tool_name"], "query_runtime_history")
        self.assertEqual(result["data"][0]["payload"]["count"], 8)

    def test_only_declared_read_actions_are_allowed(self) -> None:
        result = self.agent.run({"action": "config.write", "arguments": {}})
        self.assertEqual(result["status"], "error")
        self.assertIn("read-only", result["summary"])

    def test_single_intersection_signal_timing_action(self) -> None:
        result = self.agent_with_signal_tool.run(
            {
                "action": "signal.timing.single",
                "arguments": {"cross_id": "1300068"},
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["meta"]["tool_name"], "generate_single_intersection_signal_timing")
        self.assertEqual(result["data"]["signal_timing"], [10, 20])

    def test_qwen_agent_selects_signal_timing_tool(self) -> None:
        result = self.qwen_agent.run(
            {
                "cross_id": "1300068",
                "request_text": "请给出当前路口的放行方案",
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["meta"]["tool_name"], "generate_single_intersection_signal_timing")
        self.assertEqual(result["data"]["tool_result"]["data"]["signal_timing"], [10, 20])
        self.assertIn("放行方案", result["summary"])


if __name__ == "__main__":
    unittest.main()
