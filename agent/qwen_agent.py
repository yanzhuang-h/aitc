"""Qwen 编排层。

保留结构化动作路由，并新增基于 OpenAI 兼容模型服务的自然语言调用链。
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from app.core.models import ToolResponse
from app.infrastructure.llm import OpenAICompatibleLLMClient

from .tools import DataQueryTools


class SymbolicDataAgent:
    """基于明确动作名称的只读数据查询 Agent。"""

    _ACTION_TO_TOOL = {
        "runtime.recent": "query_recent_runtime_data",
        "runtime.history": "query_runtime_history",
        "results.latest": "query_latest_results",
        "config.snapshot": "query_config_snapshot",
        "signal.timing.single": "generate_single_intersection_signal_timing",
    }

    def __init__(self, tools: DataQueryTools) -> None:
        self.tools = tools
        # 优先使用统一注册中心维护的动作映射，未提供时回退到内置映射
        self._action_to_tool = (
            dict(tools.actions()) if hasattr(tools, "actions") else dict(self._ACTION_TO_TOOL)
        )

    def run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        if not isinstance(action, str):
            return self._error("action must be a string")

        tool_name = self._action_to_tool.get(action)
        if tool_name is None:
            return self._error(f"unsupported read-only action: {action}")

        arguments = request.get("arguments", {})
        if not isinstance(arguments, Mapping):
            return self._error("arguments must be an object")

        result = self.tools.invoke(tool_name, arguments)
        response = ToolResponse(
            status=result["status"],
            summary=result["summary"],
            data=result["data"],
            meta=result.get("meta", {}),
        )
        return response.with_meta(action=action, tool_name=tool_name).to_dict()

    def action_schemas(self) -> list[dict[str, Any]]:
        tool_schemas = {item["name"]: item for item in self.tools.tool_schemas()}
        return [
            {
                "action": action,
                "tool_name": tool_name,
                "parameters": tool_schemas[tool_name]["parameters"],
            }
            for action, tool_name in self._action_to_tool.items()
            if tool_name in tool_schemas
        ]

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return ToolResponse.error(message).to_dict()


class QwenSignalTimingAgent:
    """让 Qwen 先选工具，再调用现有单路口方案工具。"""

    def __init__(self, llm_client: OpenAICompatibleLLMClient, tools: DataQueryTools) -> None:
        self.llm_client = llm_client
        self.tools = tools
        self.symbolic_agent = SymbolicDataAgent(tools)

    def run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        request_text = request.get("request_text")
        cross_id = request.get("cross_id")
        if not isinstance(request_text, str) or not request_text.strip():
            return ToolResponse.error("request_text must be a non-empty string").to_dict()
        if not isinstance(cross_id, str) or not cross_id.strip():
            return ToolResponse.error("cross_id must be a non-empty string").to_dict()

        request_text = request_text.strip()
        cross_id = cross_id.strip()

        action_request = self._choose_action(request_text, cross_id)
        action = action_request.get("action")
        arguments = action_request.get("arguments")
        if not isinstance(action, str):
            action = "signal.timing.single"
        if not isinstance(arguments, Mapping):
            arguments = {}

        tool_arguments = dict(arguments)
        tool_arguments.setdefault("cross_id", cross_id)
        tool_arguments.setdefault("request_text", request_text)

        tool_result = self.symbolic_agent.run({"action": action, "arguments": tool_arguments})
        answer = self._summarize_answer(request_text, cross_id, action, tool_result)
        return ToolResponse.ok(
            summary=answer,
            data={
                "request_text": request_text,
                "cross_id": cross_id,
                "action": action,
                "tool_result": tool_result,
                "answer": answer,
            },
            meta={
                "tool_name": tool_result.get("meta", {}).get("tool_name"),
                "llm_model": getattr(self.llm_client, "model", None),
            },
        ).to_dict()

    def _choose_action(self, request_text: str, cross_id: str) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是交通信号控制助手。只返回 JSON，对应字段为 action 和 arguments。"
                    "可用 action 仅限 signal.timing.single。"
                    "如果用户在询问某个路口的放行方案，请把 cross_id 放入 arguments。"
                ),
            },
            {
                "role": "user",
                "content": f"路口编号：{cross_id}\n需求：{request_text}",
            },
        ]
        try:
            result = self.llm_client.chat(messages, temperature=0.2, top_p=0.9, max_tokens=256)
            parsed = self._parse_json(result.content)
            if isinstance(parsed, dict):
                parsed.setdefault("action", "signal.timing.single")
                parsed.setdefault("arguments", {})
                return parsed
        except Exception:
            pass
        return {"action": "signal.timing.single", "arguments": {"cross_id": cross_id, "request_text": request_text}}

    def _summarize_answer(self, request_text: str, cross_id: str, action: str, tool_result: dict[str, Any]) -> str:
        messages = [
            {
                "role": "system",
                "content": "你是交通信号方案助手。请根据工具结果，用简洁中文给出最终答案，不要输出 JSON。",
            },
            {
                "role": "user",
                "content": (
                    f"用户需求：{request_text}\n"
                    f"路口编号：{cross_id}\n"
                    f"动作：{action}\n"
                    f"工具结果：{tool_result}"
                ),
            },
        ]
        try:
            result = self.llm_client.chat(messages, temperature=0.4, top_p=0.9, max_tokens=512)
            if result.content.strip():
                return result.content.strip()
        except Exception:
            pass
        return tool_result.get("summary", "已生成放行方案。")

    @staticmethod
    def _parse_json(content: str) -> Any:
        text = content.strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except Exception:
            return None


class QwenToolRouterAgent:
    """多工具路由：Qwen 从全部注册工具中按自然语言选工具并调用。

    与 ``QwenSignalTimingAgent`` 的区别：不再限制单一动作，而是把
    统一注册中心（数据查询 + 信号控制）的全部工具 schema 交给模型，
    由模型返回 ``{"tool_name": ..., "arguments": {...}}`` 后统一调用。
    ``cross_id`` 为可选上下文：仅当所选工具声明了 ``cross_id`` 参数时才注入。
    """

    def __init__(self, llm_client: OpenAICompatibleLLMClient, tools: DataQueryTools) -> None:
        self.llm_client = llm_client
        self.tools = tools

    @staticmethod
    def _parse_json(content: str) -> Any:
        text = content.strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except Exception:
            return None

    def run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        request_text = request.get("request_text")
        if not isinstance(request_text, str) or not request_text.strip():
            return ToolResponse.error("request_text must be a non-empty string").to_dict()
        request_text = request_text.strip()
        cross_id = request.get("cross_id")
        cross_id = cross_id.strip() if isinstance(cross_id, str) and cross_id.strip() else None

        choice = self._choose_tool(request_text, cross_id)
        tool_name = choice.get("tool_name")
        arguments = choice.get("arguments")
        if not isinstance(tool_name, str) or not tool_name.strip():
            return ToolResponse.error("模型未能从工具中选择可用工具").to_dict()
        tool_name = tool_name.strip()
        if tool_name not in self.tools.registry:
            return ToolResponse.error(f"模型选择了未知工具：{tool_name}").to_dict()
        if not isinstance(arguments, Mapping):
            arguments = {}

        tool_arguments = dict(arguments)
        # 仅注入所选工具 schema 声明过的参数，避免向严格签名工具多传参数
        spec = next(s for s in self.tools.registry.all_specs() if s.name == tool_name)
        properties = spec.parameters.get("properties", {})
        if cross_id and "cross_id" in properties:
            tool_arguments.setdefault("cross_id", cross_id)

        tool_result = self.tools.invoke(tool_name, tool_arguments)
        answer = self._summarize_answer(request_text, tool_name, tool_result)
        return ToolResponse.ok(
            summary=answer,
            data={
                "request_text": request_text,
                "cross_id": cross_id,
                "tool_name": tool_name,
                "tool_result": tool_result,
                "answer": answer,
            },
            meta={
                "tool_name": tool_name,
                "llm_model": getattr(self.llm_client, "model", None),
            },
        ).to_dict()

    def _choose_tool(self, request_text: str, cross_id: str | None) -> dict[str, Any]:
        schemas = json.dumps(self.tools.tool_schemas(), ensure_ascii=False)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是交通信号控制助手。请根据用户需求，从下列工具中选择最合适的一个，"
                    "只返回 JSON：{\"tool_name\": \"...\", \"arguments\": {...}}。"
                    "arguments 必须与所选工具的 parameters 匹配，没有把握的参数不要填写。"
                    f"\n可用工具：\n{schemas}"
                ),
            },
            {
                "role": "user",
                "content": f"路口编号（可为空）：{cross_id or '无'}\n需求：{request_text}",
            },
        ]
        try:
            result = self.llm_client.chat(messages, temperature=0.2, top_p=0.9, max_tokens=512)
            parsed = self._parse_json(result.content)
            if isinstance(parsed, dict) and isinstance(parsed.get("tool_name"), str):
                parsed.setdefault("arguments", {})
                return parsed
        except Exception:
            pass
        return {"tool_name": "", "arguments": {}}

    def _summarize_answer(
        self,
        request_text: str,
        tool_name: str,
        tool_result: dict[str, Any],
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": "你是交通信号方案助手。请根据工具结果，用简洁中文给出最终答案，不要输出 JSON。",
            },
            {
                "role": "user",
                "content": (
                    f"用户需求：{request_text}\n"
                    f"所选工具：{tool_name}\n"
                    f"工具结果：{tool_result}"
                ),
            },
        ]
        try:
            result = self.llm_client.chat(messages, temperature=0.4, top_p=0.9, max_tokens=512)
            if result.content.strip():
                return result.content.strip()
        except Exception:
            pass
        return tool_result.get("summary", "已生成结果。") if isinstance(tool_result, dict) else "已生成结果。"
