"""Agent Harness：Agent 的统一运行载体。

职责边界（参考 agent + harness 架构）：
- Agent（``agent/qwen_agent.py``、``agent/control_agent.py``）：只负责决策与编排，
  接收结构化请求、返回结构化结果（ToolResponse），不感知协议。
- Harness（本模块）：负责统一入口、意图路由、请求校验、错误处理，
  以及协议层（HTTP/TCP）与 Agent / 工具之间的适配。

协议层（如 HTTP handler）只依赖本门面，不再直接依赖具体 Agent 或工具；
新增 Agent 时只需在 ``handle()`` 中登记一条路由。
"""

from __future__ import annotations

from typing import Any, Mapping

from app.core.models import ToolResponse


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
        logger: Any | None = None,
    ) -> None:
        self.signal_timing_tool = signal_timing_tool
        self.symbolic_agent = symbolic_agent
        self.qwen_agent = qwen_agent
        self.control_process_agent = control_process_agent
        self.qwen_tool_router_agent = qwen_tool_router_agent
        self.logger = logger

    def handle(self, intent: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """按意图路由到对应 Agent / 工具，返回既有协议结构。"""
        if intent == "signal_timing":
            return self._handle_signal_timing(payload)
        if intent == "agent.signal_timing":
            return self._handle_qwen_signal_timing(payload)
        if intent == "control_process":
            return self._handle_control_process(payload)
        if intent == "symbolic":
            return self._handle_symbolic(payload)
        if intent == "agent.tools":
            return self._handle_qwen_tools(payload)
        raise ValueError(f"unsupported agent intent: {intent}")

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
