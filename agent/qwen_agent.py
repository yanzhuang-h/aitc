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

    def run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        if not isinstance(action, str):
            return self._error("action must be a string")

        tool_name = self._ACTION_TO_TOOL.get(action)
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
            for action, tool_name in self._ACTION_TO_TOOL.items()
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
