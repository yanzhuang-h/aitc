"""Agent Harness：Agent 的统一运行载体。

职责边界（参考 agent + harness 架构）：
- Agent（``agent/qwen_agent.py``、``agent/control_agent.py``）：只负责决策与编排，
  接收结构化请求、返回结构化结果（ToolResponse），不感知协议。
- Harness（本模块）：负责统一入口、意图路由、请求校验、错误处理，
  以及协议层（HTTP/TCP）与 Agent / 工具之间的适配。

意图路由采用三层设计：
1. 显式意图注册表：``handle()`` 按名称精确路由到注册的处理器；
2. Agent 自主判断：未注册的意图且带自然语言请求时，交给自主判断 Agent
   从全部注册工具中自行选择；
3. 兜底逻辑：既无显式意图又无法自主判断时，返回默认响应并附可用意图清单。

协议层（如 HTTP handler）只依赖本门面，不再直接依赖具体 Agent 或工具；
新增 Agent 时只需在 ``_register_intents()`` 中登记一条意图。
"""

from __future__ import annotations

from typing import Any, Mapping

from app.core.models import ToolResponse

from .registry import IntentRegistry


class AgentHarness:
    """统一调度 Agent 与工具的门面。

    ``handle(intent, payload)`` 是协议层唯一入口，返回与既有 HTTP 响应
    完全一致的结构（向后兼容，不改变链路行为）。
    """

    def __init__(
        self,
        *,
        signal_timing_tool: Any | None = None,
        symbolic_agent: Any | None = None,
        qwen_agent: Any | None = None,
        control_process_agent: Any | None = None,
        qwen_tool_router_agent: Any | None = None,
        autonomous_agent: Any | None = None,
        intent_registry: IntentRegistry | None = None,
        logger: Any | None = None,
    ) -> None:
        self.signal_timing_tool = signal_timing_tool
        self.symbolic_agent = symbolic_agent
        self.qwen_agent = qwen_agent
        self.control_process_agent = control_process_agent
        self.qwen_tool_router_agent = qwen_tool_router_agent
        # 自主判断 Agent：默认复用多工具路由 Agent
        self.autonomous_agent = (
            autonomous_agent if autonomous_agent is not None else qwen_tool_router_agent
        )
        self.intent_registry = (
            intent_registry if intent_registry is not None else IntentRegistry()
        )
        self.logger = logger
        self._register_intents()

    def _register_intents(self) -> None:
        """注册内置意图；新增意图只需在此登记。"""
        self.intent_registry.register(
            "signal_timing",
            "直连单路口方案工具（不经 LLM）",
            self._handle_signal_timing,
        )
        self.intent_registry.register(
            "agent.signal_timing",
            "Qwen 先选工具、再调用单路口方案工具",
            self._handle_qwen_signal_timing,
        )
        self.intent_registry.register(
            "control_process",
            "分步放行控制：规则判断 + LLM 逐步思考",
            self._handle_control_process,
        )
        self.intent_registry.register(
            "symbolic",
            "符号动作路由（只读数据查询）",
            self._handle_symbolic,
        )
        self.intent_registry.register(
            "agent.tools",
            "多工具路由：从全部注册工具中按自然语言选择",
            self._handle_qwen_tools,
        )
        self.intent_registry.register(
            "autonomous",
            "Agent 自主判断：按自然语言选择最合适工具",
            self._handle_autonomous,
        )

    def handle(self, intent: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """按意图路由：显式意图 -> 自主判断 -> 兜底。返回既有协议结构。"""
        spec = self.intent_registry.get(intent)
        if spec is not None:
            return spec.handler(payload)
        return self._handle_unregistered(intent, payload)

    def intent_list(self) -> list[dict[str, str]]:
        """返回已注册意图清单，供调试与前端展示。"""
        return self.intent_registry.describe()

    # ---- 意图处理器 ------------------------------------------------------

    def _handle_signal_timing(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """直连单路口方案工具（不经 LLM）。"""
        if self.signal_timing_tool is None:
            raise RuntimeError("signal timing tool is not configured")
        cross_id = self._require_cross_id(payload)
        request_body = dict(payload)
        request_body.pop("cross_id", None)
        result = self.signal_timing_tool.generate(cross_id=cross_id, **request_body)
        return {"status": "success", "cross_id": cross_id, "result": result}

    def _handle_qwen_signal_timing(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Qwen 先选工具、再调用单路口方案工具。"""
        if self.qwen_agent is None:
            raise RuntimeError("qwen agent is not configured")
        cross_id = self._require_cross_id(payload)
        request_text = self._require_text(payload, "request_text")
        result = self.qwen_agent.run(
            {"request_text": request_text, "cross_id": cross_id}
        )
        return {"status": "success", "cross_id": cross_id, "result": result}

    def _handle_control_process(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """分步放行控制：规则判断 + LLM 逐步思考。"""
        if self.control_process_agent is None:
            raise RuntimeError("control process agent is not configured")
        cross_id = self._require_cross_id(payload)
        result = self.control_process_agent.run(
            {"cross_id": cross_id, "request_text": payload.get("request_text")}
        )
        return {"status": "success", "cross_id": cross_id, "result": result}

    def _handle_symbolic(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """符号动作路由（只读数据查询）。"""
        if self.symbolic_agent is None:
            raise RuntimeError("symbolic agent is not configured")
        result = self.symbolic_agent.run(dict(payload))
        return {"status": "success", "result": result}

    def _handle_qwen_tools(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """多工具路由：Qwen 从全部注册工具中按自然语言选工具并调用。"""
        if self.qwen_tool_router_agent is None:
            raise RuntimeError("qwen tool router agent is not configured")
        request_text = self._require_text(payload, "request_text")
        request: dict[str, Any] = {"request_text": request_text}
        cross_id = payload.get("cross_id")
        if isinstance(cross_id, str) and cross_id.strip():
            request["cross_id"] = cross_id.strip()
        result = self.qwen_tool_router_agent.run(request)
        return {"status": "success", "cross_id": request.get("cross_id"), "result": result}

    def _handle_autonomous(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Agent 自主判断：按自然语言从全部工具中选择并调用。"""
        if self.autonomous_agent is None:
            raise RuntimeError("autonomous agent is not configured")
        request_text = self._require_text(payload, "request_text")
        request: dict[str, Any] = {"request_text": request_text}
        cross_id = payload.get("cross_id")
        if isinstance(cross_id, str) and cross_id.strip():
            request["cross_id"] = cross_id.strip()
        result = self.autonomous_agent.run(request)
        return {
            "status": "success",
            "cross_id": request.get("cross_id"),
            "routed_by": "autonomous",
            "result": result,
        }

    def _handle_unregistered(self, intent: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """未注册意图的三层兜底：先尝试自主判断，再返回默认响应。"""
        # 自主判断：带自然语言请求且自主 Agent 可用时，让 Agent 自行选择工具
        if self.autonomous_agent is not None:
            request_text = payload.get("request_text")
            if isinstance(request_text, str) and request_text.strip():
                result = self._handle_autonomous(payload)
                result["fallback_intent"] = intent
                return result
        # 兜底：返回默认响应并附可用意图清单
        return {
            "status": "error",
            "result": ToolResponse.error(
                f"未识别的意图：{intent}",
                meta={"available_intents": self.intent_registry.describe()},
            ).to_dict(),
        }

    # ---- 请求校验 --------------------------------------------------------

    @staticmethod
    def _require_cross_id(payload: Mapping[str, Any]) -> str:
        cross_id = payload.get("cross_id")
        if not isinstance(cross_id, str) or not cross_id.strip():
            raise ValueError("cross_id must be a non-empty string")
        return cross_id.strip()

    @staticmethod
    def _require_text(payload: Mapping[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        return value.strip()

    def _error(self, message: str) -> dict[str, Any]:
        return ToolResponse.error(message).to_dict()
