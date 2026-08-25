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

import time
from collections import deque
from typing import Any, Mapping

from app.core.models import ToolResponse

from .registry import IntentRegistry


class AgentHarness:
    """统一调度 Agent 与工具的门面。

    ``handle(intent, payload)`` 是协议层唯一入口，返回与既有 HTTP 响应
    完全一致的结构（向后兼容，不改变链路行为）。
    每次调用都会记录一条可观测日志（意图、路由方式、耗时、状态）。
    """

    #: 调用日志环形缓冲上限
    CALL_LOG_MAX = 200

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
        green_wave_service: Any | None = None,
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
        self.green_wave_service = green_wave_service
        self.logger = logger
        self._call_log: deque[dict[str, Any]] = deque(maxlen=self.CALL_LOG_MAX)
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
        self.intent_registry.register(
            "green_wave.status",
            "绿波协调当前运行状态",
            self._handle_green_wave_status,
        )
        self.intent_registry.register(
            "green_wave.config",
            "绿波走廊配置：未指定 corridor_id 返回全部，指定返回单条",
            self._handle_green_wave_config,
        )
        self.intent_registry.register(
            "green_wave.plan",
            "最新一轮实际下发的绿波方案",
            self._handle_green_wave_plan,
        )
        self.intent_registry.register(
            "green_wave.list",
            "绿波走廊列表：full=false 摘要，full=true 完整",
            self._handle_green_wave_list,
        )
        self.intent_registry.register(
            "green_wave.get",
            "查询指定绿波走廊完整配置",
            self._handle_green_wave_get,
        )
        self.intent_registry.register(
            "green_wave.validate",
            "只校验绿波走廊配置，不保存（支持文档1/文档2）",
            self._handle_green_wave_validate,
        )
        self.intent_registry.register(
            "green_wave.update",
            "新增或更新绿波走廊配置并保存（支持文档1/文档2）",
            self._handle_green_wave_update,
        )
        self.intent_registry.register(
            "green_wave.delete",
            "删除绿波走廊（转停用，配置保留）",
            self._handle_green_wave_delete,
        )
        self.intent_registry.register(
            "green_wave.enabled",
            "启用或停用一条绿波走廊",
            self._handle_green_wave_enabled,
        )

    def handle(self, intent: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """按意图路由：显式意图 -> 自主判断 -> 兜底。返回既有协议结构。

        每次调用都会记录可观测日志（意图、路由方式、耗时、状态）。
        """
        start = time.monotonic()
        try:
            spec = self.intent_registry.get(intent)
            if spec is not None:
                result = spec.handler(payload)
                routed_by = "registry"
            else:
                result = self._handle_unregistered(intent, payload)
                routed_by = result.get("routed_by") if isinstance(result, dict) else None
                routed_by = routed_by if routed_by in ("autonomous", "fallback") else "fallback"
            self._record_call(intent, routed_by, result, start)
            return result
        except Exception as error:
            self._record_call(intent, "registry", None, start, error=str(error))
            raise

    def intent_list(self) -> list[dict[str, str]]:
        """返回已注册意图清单，供调试与前端展示。"""
        return self.intent_registry.describe()

    def recent_calls(self, limit: int = 20) -> list[dict[str, Any]]:
        """返回最近调用可观测记录（意图、路由方式、耗时、状态）。"""
        limit = max(1, min(int(limit or 20), self.CALL_LOG_MAX))
        return list(self._call_log)[-limit:]

    def _record_call(
        self,
        intent: str,
        routed_by: str,
        result: dict[str, Any] | None,
        start: float,
        *,
        error: str | None = None,
    ) -> None:
        """记录一次调用：路由方式 + 耗时 + 结果状态。"""
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        status = "error" if error else (result or {}).get("status", "unknown")
        self._call_log.append(
            {
                "ts": round(time.time(), 3),
                "intent": intent,
                "routed_by": routed_by,
                "status": status,
                "duration_ms": duration_ms,
                "error": error,
            }
        )

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
    def _require_str(payload: Mapping[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _require_cross_id(payload: Mapping[str, Any]) -> str:
        return AgentHarness._require_str(payload, "cross_id")

    @staticmethod
    def _require_text(payload: Mapping[str, Any], key: str) -> str:
        return AgentHarness._require_str(payload, key)

    # ---- 绿波意图（委托 GreenWaveDataService）--------------------------

    def _green_wave(self) -> Any:
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service

    def _handle_green_wave_status(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._green_wave().status()

    def _handle_green_wave_config(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._green_wave().config(payload.get("corridor_id"))

    def _handle_green_wave_plan(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._green_wave().plan()

    def _handle_green_wave_list(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._green_wave().list_corridors(full=bool(payload.get("full", False)))

    def _handle_green_wave_get(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        corridor_id = self._require_str(payload, "corridor_id")
        return self._green_wave().get_corridor(corridor_id)

    def _handle_green_wave_validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._green_wave().validate_corridor(payload)

    def _handle_green_wave_update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._green_wave().update_corridor(payload)

    def _handle_green_wave_delete(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        corridor_id = self._require_str(payload, "corridor_id")
        return self._green_wave().delete_corridor(corridor_id)

    def _handle_green_wave_enabled(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        corridor_id = self._require_str(payload, "corridor_id")
        enabled = bool(payload.get("enabled", False))
        return self._green_wave().set_corridor_enabled(corridor_id, enabled)

    def _error(self, message: str) -> dict[str, Any]:
        return ToolResponse.error(message).to_dict()
