"""符号主义 Agent 与数据底座完整链路测试。"""

from __future__ import annotations

import tempfile
import unittest

from agent.qwen_agent import QwenSignalTimingAgent, QwenToolRouterAgent, SymbolicDataAgent
from agent.harness import AgentHarness
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


class _RouterLLMClient:
    """多工具路由 mock：第一次返回工具选择 JSON，第二次返回汇总答案。"""

    model = "fake-qwen"

    def __init__(self, tool_choice: str):
        self.tool_choice = tool_choice
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if len(self.calls) == 1:
            return _ChatResult(self.tool_choice)
        return _ChatResult("已根据需求完成工具调用。")


class _GreenWaveService:
    """绿波服务 mock：记录调用参数并返回固定成功结构。"""

    def __init__(self):
        self.calls = []

    def status(self):
        self.calls.append(("status",))
        return {"status": "success", "running": True}

    def config(self, corridor_id=None):
        self.calls.append(("config", corridor_id))
        return {"status": "success", "items": []}

    def plan(self):
        self.calls.append(("plan",))
        return {"status": "success", "plan": {}}

    def list_corridors(self, full=False):
        self.calls.append(("list", full))
        return {"status": "success", "items": []}

    def get_corridor(self, corridor_id):
        self.calls.append(("get", corridor_id))
        return {"status": "success", "corridor_id": corridor_id}

    def validate_corridor(self, body):
        self.calls.append(("validate", body))
        return {"status": "success", "validated": True}

    def update_corridor(self, body):
        self.calls.append(("update", body))
        return {"status": "success", "saved": True}

    def delete_corridor(self, corridor_id):
        self.calls.append(("delete", corridor_id))
        return {"status": "success", "enabled": False}

    def set_corridor_enabled(self, corridor_id, enabled):
        self.calls.append(("enabled", corridor_id, enabled))
        return {"status": "success", "enabled": enabled}


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
        self.data_tools = DataQueryTools(query_service, signal_timing_tool=signal_tool)

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

    # ---- 多工具路由（QwenToolRouterAgent + AgentHarness.agent.tools）----

    def test_tool_router_selects_query_tool_without_cross_id_injection(self) -> None:
        """模型选查询工具（无 cross_id 参数），不得注入 cross_id 导致多参。"""
        router = QwenToolRouterAgent(
            _RouterLLMClient('{"tool_name":"query_latest_results","arguments":{"limit":3}}'),
            self.data_tools,
        )
        result = router.run({"request_text": "查询最新决策结果", "cross_id": "1300068"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["meta"]["tool_name"], "query_latest_results")
        self.assertEqual(result["data"]["tool_result"]["status"], "ok")
        self.assertIn("已根据需求完成工具调用", result["summary"])

    def test_tool_router_selects_signal_tool_with_cross_id(self) -> None:
        """模型选信号控制工具（声明了 cross_id），自动注入路口编号。"""
        router = QwenToolRouterAgent(
            _RouterLLMClient(
                '{"tool_name":"generate_single_intersection_signal_timing","arguments":{}}'
            ),
            self.data_tools,
        )
        result = router.run({"request_text": "生成放行方案", "cross_id": "1300068"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["meta"]["tool_name"], "generate_single_intersection_signal_timing")
        self.assertEqual(result["data"]["tool_result"]["data"]["signal_timing"], [10, 20])

    def test_tool_router_rejects_unknown_tool(self) -> None:
        router = QwenToolRouterAgent(
            _RouterLLMClient('{"tool_name":"not_exist_tool","arguments":{}}'),
            self.data_tools,
        )
        result = router.run({"request_text": "任意需求"})
        self.assertEqual(result["status"], "error")
        self.assertIn("未知工具", result["summary"])

    def test_harness_routes_agent_tools_intent(self) -> None:
        harness = AgentHarness(
            qwen_tool_router_agent=QwenToolRouterAgent(
                _RouterLLMClient(
                    '{"tool_name":"query_latest_results","arguments":{"limit":2}}'
                ),
                self.data_tools,
            ),
        )
        result = harness.handle(
            "agent.tools",
            {"request_text": "看看最新结果", "cross_id": "1300068"},
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cross_id"], "1300068")
        self.assertEqual(result["result"]["meta"]["tool_name"], "query_latest_results")

    def test_harness_agent_tools_requires_request_text(self) -> None:
        harness = AgentHarness(
            qwen_tool_router_agent=QwenToolRouterAgent(_RouterLLMClient("{}"), self.data_tools),
        )
        with self.assertRaises(ValueError):
            harness.handle("agent.tools", {"cross_id": "1300068"})

    # ---- 意图注册表 + 三层路由（显式 / 自主判断 / 兜底）----

    def test_intent_registry_basics(self) -> None:
        from agent.registry import IntentRegistry

        registry = IntentRegistry()
        registry.register("a", "A 描述", lambda payload: {"status": "success"})
        self.assertIn("a", registry)
        self.assertEqual(registry.get("a").description, "A 描述")
        self.assertEqual([i["name"] for i in registry.describe()], ["a"])
        self.assertIsNone(registry.get("missing"))
        self.assertEqual(len(registry), 1)

    def test_harness_registered_intent_goes_through_registry(self) -> None:
        """已注册意图走注册表精确路由（仍兼容旧行为）。"""
        harness = AgentHarness(
            qwen_tool_router_agent=QwenToolRouterAgent(
                _RouterLLMClient(
                    '{"tool_name":"query_latest_results","arguments":{"limit":2}}'
                ),
                self.data_tools,
            ),
        )
        result = harness.handle(
            "agent.tools",
            {"request_text": "看看最新结果", "cross_id": "1300068"},
        )
        self.assertEqual(result["status"], "success")
        self.assertNotIn("routed_by", result)  # 显式意图不标记自主路由
        self.assertEqual(result["result"]["meta"]["tool_name"], "query_latest_results")

    def test_harness_unknown_intent_autonomous_routing(self) -> None:
        """未注册意图 + 自然语言 -> 交由 Agent 自主判断。"""
        harness = AgentHarness(
            qwen_tool_router_agent=QwenToolRouterAgent(
                _RouterLLMClient(
                    '{"tool_name":"query_latest_results","arguments":{}}'
                ),
                self.data_tools,
            ),
        )
        result = harness.handle(
            "随便说点什么",
            {"request_text": "看看最新结果", "cross_id": "1300068"},
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["routed_by"], "autonomous")
        self.assertEqual(result["fallback_intent"], "随便说点什么")
        self.assertEqual(result["result"]["meta"]["tool_name"], "query_latest_results")

    def test_harness_unknown_intent_fallback(self) -> None:
        """未注册意图且无自然语言 -> 兜底默认响应 + 可用意图清单。"""
        harness = AgentHarness(
            qwen_tool_router_agent=QwenToolRouterAgent(_RouterLLMClient("{}"), self.data_tools),
        )
        result = harness.handle("no_such_intent", {"cross_id": "1300068"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["result"]["status"], "error")
        self.assertIn("未识别的意图", result["result"]["summary"])
        names = [i["name"] for i in result["result"]["meta"]["available_intents"]]
        self.assertIn("agent.tools", names)
        self.assertIn("autonomous", names)

    def test_harness_autonomous_intent(self) -> None:
        """显式 autonomous 意图 -> 自主判断。"""
        harness = AgentHarness(
            qwen_tool_router_agent=QwenToolRouterAgent(
                _RouterLLMClient(
                    '{"tool_name":"query_latest_results","arguments":{}}'
                ),
                self.data_tools,
            ),
        )
        result = harness.handle(
            "autonomous",
            {"request_text": "最新结果", "cross_id": "1300068"},
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["routed_by"], "autonomous")
        self.assertEqual(result["result"]["meta"]["tool_name"], "query_latest_results")

    # ---- 绿波意图组（green_wave.*）----

    def test_harness_green_wave_read_intents(self) -> None:
        service = _GreenWaveService()
        harness = AgentHarness(green_wave_service=service)

        result = harness.handle("green_wave.status", {})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["running"], True)

        result = harness.handle("green_wave.config", {"corridor_id": "lvbo_01"})
        self.assertEqual(service.calls[-1], ("config", "lvbo_01"))

        result = harness.handle("green_wave.config", {})
        self.assertEqual(service.calls[-1], ("config", None))

        result = harness.handle("green_wave.plan", {})
        self.assertEqual(service.calls[-1], ("plan",))

        result = harness.handle("green_wave.list", {"full": True})
        self.assertEqual(service.calls[-1], ("list", True))

    def test_harness_green_wave_get_and_enabled(self) -> None:
        service = _GreenWaveService()
        harness = AgentHarness(green_wave_service=service)

        result = harness.handle("green_wave.get", {"corridor_id": "lvbo_01"})
        self.assertEqual(result["corridor_id"], "lvbo_01")
        self.assertEqual(service.calls[-1], ("get", "lvbo_01"))

        result = harness.handle(
            "green_wave.enabled", {"corridor_id": "lvbo_01", "enabled": False}
        )
        self.assertEqual(service.calls[-1], ("enabled", "lvbo_01", False))

        result = harness.handle("green_wave.delete", {"corridor_id": "lvbo_01"})
        self.assertEqual(service.calls[-1], ("delete", "lvbo_01"))

    def test_harness_green_wave_requires_corridor_id(self) -> None:
        harness = AgentHarness(green_wave_service=_GreenWaveService())
        with self.assertRaises(ValueError):
            harness.handle("green_wave.get", {})

    def test_harness_green_wave_without_service_raises(self) -> None:
        bare = AgentHarness()
        with self.assertRaises(RuntimeError):
            bare.handle("green_wave.status", {})


if __name__ == "__main__":
    unittest.main()
