"""Agent 访问数据底座的只读工具契约。"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from infra.data import MemoryQueryLayer


class DataQueryTools:
    """为 Agent 提供受限的运行数据、结果和配置查询能力。"""

    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100
    SUMMARY = "summary"
    FULL = "full"

    _TOOL_SCHEMAS = [
        {
            "name": "query_recent_runtime_data",
            "description": "查询指定类型的近期运行数据窗口。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "数据类型，例如 flow、queue、radar。"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                    "detail": {"type": "string", "enum": [SUMMARY, FULL]},
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
                    "detail": {"type": "string", "enum": [SUMMARY, FULL]},
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
                    "detail": {"type": "string", "enum": [SUMMARY, FULL]},
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
                    "detail": {"type": "string", "enum": [SUMMARY, FULL]},
                },
                "required": ["resource"],
            },
        },
    ]

    def __init__(self, query_service: MemoryQueryLayer) -> None:
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

    def query_recent_runtime_data(
        self,
        kind: str,
        limit: int = DEFAULT_LIMIT,
        detail: str = SUMMARY,
    ) -> dict[str, Any]:
        """查询实时窗口数据。"""
        try:
            records = self.query_service.get_runtime_data(kind, limit=self._limit(limit))
            normalized_detail = self._detail(detail)
            return self._success(
                f"已获取 {len(records)} 条 {kind} 实时数据。",
                self._format_records(records, normalized_detail),
                {"kind": kind, "source": "runtime_cache", "detail": normalized_detail},
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
        detail: str = SUMMARY,
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
            normalized_detail = self._detail(detail)
            return self._success(
                f"已获取 {len(records)} 条 {kind} 历史数据。",
                self._format_records(records, normalized_detail),
                {
                    "kind": kind,
                    "intersection_id": intersection_id,
                    "start_at": start_at,
                    "end_at": end_at,
                    "source": "runtime_repository",
                    "detail": normalized_detail,
                },
            )
        except (ValueError, RuntimeError) as error:
            return self._error(str(error))

    def query_latest_results(
        self,
        limit: int = DEFAULT_LIMIT,
        detail: str = SUMMARY,
    ) -> dict[str, Any]:
        """查询最新决策结果。"""
        try:
            results = self.query_service.get_latest_results()[-self._limit(limit):]
            normalized_detail = self._detail(detail)
            return self._success(
                f"已获取 {len(results)} 条最新决策结果。",
                self._format_records(results, normalized_detail),
                {"source": "result_warehouse", "detail": normalized_detail},
            )
        except (ValueError, RuntimeError) as error:
            return self._error(str(error))

    def query_config_snapshot(
        self,
        resource: str,
        cross_id: str | None = None,
        detail: str = SUMMARY,
    ) -> dict[str, Any]:
        """查询配置快照。"""
        try:
            data = self.query_service.get_config_snapshot(resource, cross_id=cross_id)
            normalized_detail = self._detail(detail)
            return self._success(
                f"已获取 {resource} 配置快照。",
                self._format_config(data, normalized_detail),
                {
                    "resource": resource,
                    "cross_id": cross_id,
                    "source": "config_service",
                    "detail": normalized_detail,
                },
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

    @classmethod
    def _detail(cls, value: str) -> str:
        if value not in {cls.SUMMARY, cls.FULL}:
            raise ValueError("detail must be summary or full")
        return value

    @classmethod
    def _format_records(cls, records: list[dict[str, Any]], detail: str) -> Any:
        if detail == cls.FULL:
            return records
        return {
            "count": len(records),
            "items": [cls._record_summary(record) for record in records],
        }

    @staticmethod
    def _record_summary(record: Mapping[str, Any]) -> dict[str, Any]:
        payload = record.get("payload")
        source = payload if isinstance(payload, Mapping) else record
        identifiers = {
            key: source[key]
            for key in ("Cross_id", "CrossId", "cross_id", "intersection_id", "inter_id", "deviceNo", "deviceId", "jtll_ddbh")
            if key in source
        }
        return {
            "kind": record.get("kind"),
            "intersection_id": record.get("intersection_id") or identifiers.get("intersection_id"),
            "source": record.get("source"),
            "received_at": record.get("received_at"),
            "identifiers": identifiers,
            "fields": sorted(source.keys()),
        }

    @classmethod
    def _format_config(cls, data: Any, detail: str) -> Any:
        if detail == cls.FULL:
            return data
        if isinstance(data, Mapping):
            return {"type": "object", "key_count": len(data), "keys": sorted(map(str, data.keys()))[:20]}
        if isinstance(data, list):
            return {"type": "list", "item_count": len(data)}
        return {"type": type(data).__name__, "value": data}

    @staticmethod
    def _success(summary: str, data: Any, meta: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "summary": summary, "data": data, "meta": meta}

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"status": "error", "summary": message, "data": None, "meta": {}}
