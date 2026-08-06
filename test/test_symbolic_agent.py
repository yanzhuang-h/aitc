"""符号主义 Agent 与数据底座完整链路测试。"""

from __future__ import annotations

import tempfile
import unittest

from agent.qwen_agent import SymbolicDataAgent
from agent.tools import DataQueryTools
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
            cache=cache,
            result_warehouse=results,
            config_service=ConfigService(),
            repository=repository,
        )
        self.agent = SymbolicDataAgent(DataQueryTools(query_service))

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


if __name__ == "__main__":
    unittest.main()
