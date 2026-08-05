"""Agent 访问数据底座的只读工具契约。"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from infra.data import RuntimeDataQueryService


class DataQueryTools:
    """为 Agent 提供受限的运行数据、结果和配置查询能力。"""

    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100

    _TOOL_SCHEMAS = [
        {
            "name": "query_recent_runtime_data",
            "description": "查询指定类型的近期运行数据窗口。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "数据类型，例如 flow、queue、radar。"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                },
                "required": ["kind"],
            },
        },
        {
            "name": "query_runtime_history",
            "description": "按数据类型、路口和接收时间范围查询持久化运行记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "intersection_id": {"type": "string"},
                    "start_at": {"type": "string", "description": "ISO 8601 起始时间。"},
                    "end_at": {"type": "string", "description": "ISO 8601 结束时间。"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                },
                "required": ["kind"],
            },
        },
        {
            "name": "query_latest_results",
            "description": "查询当前最新的路口决策结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                },
            },
        },
        {
            "name": "query_config_snapshot",
            "description": "查询配置快照；路口级配置需要提供 cross_id。",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource": {"type": "string", "description": "配置资源名称。"},
                    "cross_id": {"type": "string"},
                },
                "required": ["resource"],
            },
        },
    ]

    def __init__(self, query_service: RuntimeDataQueryService) -> None:
        self.query_service = query_service

    def tool_schemas(self) -> list[dict[str, Any]]:
        """返回可交给 Qwen 或其他工具调用框架的工具定义。"""
        return copy.deepcopy(self._TOOL_SCHEMAS)

    def invoke(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """按工具名称调用，供模型工具调用适配层使用。"""
        handlers = {
            "query_recent_runtime_data": self.query_recent_runtime_data,
            "query_runtime_history": self.query_runtime_history,
            "query_latest_results": self.query_latest_results,
            "query_config_snapshot": self.query_config_snapshot,
        }
        handler = handlers.get(name)
        if handler is None:
            return self._error(f"unknown tool: {name}")
        try:
            return handler(**dict(arguments or {}))
        except (TypeError, ValueError, RuntimeError) as error:
            return self._error(str(error))

    def query_recent_runtime_data(self, kind: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        """查询实时窗口数据。"""
        try:
            records = self.query_service.get_runtime_data(kind, limit=self._limit(limit))
            return self._success(
                f"已获取 {len(records)} 条 {kind} 实时数据。",
                records,
                {"kind": kind, "source": "runtime_cache"},
            )
        except (ValueError, RuntimeError) as error:
            return self._error(str(error))

    def query_runtime_history(
        self,
        kind: str,
        intersection_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """查询持久化运行记录。"""
        try:
            records = self.query_service.get_runtime_history(
                kind,
                limit=self._limit(limit),
                intersection_id=intersection_id,
                start_at=start_at,
                end_at=end_at,
            )
            return self._success(
                f"已获取 {len(records)} 条 {kind} 历史数据。",
                records,
                {
                    "kind": kind,
                    "intersection_id": intersection_id,
                    "start_at": start_at,
                    "end_at": end_at,
                    "source": "runtime_repository",
                },
            )
        except (ValueError, RuntimeError) as error:
            return self._error(str(error))

    def query_latest_results(self, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        """查询最新决策结果。"""
        try:
            results = self.query_service.get_latest_results()[-self._limit(limit):]
            return self._success(
                f"已获取 {len(results)} 条最新决策结果。",
                results,
                {"source": "result_warehouse"},
            )
        except (ValueError, RuntimeError) as error:
            return self._error(str(error))

    def query_config_snapshot(
        self,
        resource: str,
        cross_id: str | None = None,
    ) -> dict[str, Any]:
        """查询配置快照。"""
        try:
            data = self.query_service.get_config_snapshot(resource, cross_id=cross_id)
            return self._success(
                f"已获取 {resource} 配置快照。",
                data,
                {"resource": resource, "cross_id": cross_id, "source": "config_service"},
            )
        except (ValueError, RuntimeError) as error:
            return self._error(str(error))

    @classmethod
    def _limit(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("limit must be an integer")
        if not 1 <= value <= cls.MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {cls.MAX_LIMIT}")
        return value

    @staticmethod
    def _success(summary: str, data: Any, meta: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "summary": summary, "data": data, "meta": meta}

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"status": "error", "summary": message, "data": None, "meta": {}}
