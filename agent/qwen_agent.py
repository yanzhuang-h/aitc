"""面向未来 Qwen 接入的符号主义 Agent 运行时。

当前不依赖任何大模型 SDK。它只接受结构化动作并路由到只读数据工具，
用于验证 Agent、数据底座和工具之间的完整调用链。
"""

from __future__ import annotations

from typing import Any, Mapping

from app.core.models import ToolResponse
from .tools import DataQueryTools


class SymbolicDataAgent:
    """基于明确动作名称的确定性数据查询 Agent。"""

    _ACTION_TO_TOOL = {
        "runtime.recent": "query_recent_runtime_data",
        "runtime.history": "query_runtime_history",
        "results.latest": "query_latest_results",
        "config.snapshot": "query_config_snapshot",
    }

    def __init__(self, tools: DataQueryTools) -> None:
        self.tools = tools

    def run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """执行结构化请求。

        请求格式：``{"action": "runtime.recent", "arguments": {...}}``。
        仅路由已声明的只读动作，不接受任意函数名。
        """
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
        """返回符号动作与底层工具之间的可审计映射。"""
        tool_schemas = {item["name"]: item for item in self.tools.tool_schemas()}
        return [
            {
                "action": action,
                "tool_name": tool_name,
                "parameters": tool_schemas[tool_name]["parameters"],
            }
            for action, tool_name in self._ACTION_TO_TOOL.items()
        ]

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return ToolResponse.error(message).to_dict()
