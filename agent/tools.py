"""Agent 访问数据底座的只读工具契约。"""

from __future__ import annotations

from typing import Any, Mapping

from agent.registry import ToolRegistry
from app.core.models import ToolResponse
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
        {
            "name": "query_config_pool",
            "description": "查询长期记忆中的持久化配置池，可按命名空间或键读取。",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "key": {"type": "string"},
                    "detail": {"type": "string", "enum": [SUMMARY, FULL]},
                },
            },
        },
        {
            "name": "query_experience_pool",
            "description": "查询长期记忆中的经验池，可按分类或键读取。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "key": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                    "detail": {"type": "string", "enum": [SUMMARY, FULL]},
                },
            },
        },
        {
            "name": "generate_single_intersection_signal_timing",
            "description": "调用既有 DQN_Select 算法生成单个路口的放行时间。",
            "parameters": {
                "type": "object",
                "properties": {
                    "cross_id": {"type": "string", "description": "路口编号。"},
                    "traffic_vector": {"type": "array", "description": "路口交通流向量。"},
                    "queue_vector": {"type": "object", "description": "路口排队长度数据。"},
                    "traffic_vector_duration2": {"type": "array", "description": "指定时间窗内的交通流向量。"},
                    "flow_map": {"type": "object", "description": "路口流量时序数据。"},
                    "queue_map": {"type": "object", "description": "路口排队时序数据。"},
                    "stage_map": {"type": "object", "description": "路口相位阶段数据。"},
                    "extend_map": {"type": "object", "description": "路口扩展数据。"},
                    "overflow_map": {"type": "object", "description": "路口溢出预警数据。"},
                    "radar_map": {"type": "object", "description": "路口雷达事件数据。"},
                    "boyan_map": {"type": "object", "description": "路口博研数据。"},
                    "flow_prediction": {"type": "object", "description": "当前流量预测数据。"},
                    "queue_prediction": {"type": "object", "description": "当前排队预测数据。"},
                },
                "required": ["cross_id"],
            },
        },
    ]

    def __init__(self, query_service: MemoryQueryLayer, signal_timing_tool: Any | None = None) -> None:
        self.query_service = query_service
        self.signal_timing_tool = signal_timing_tool
        self.registry = ToolRegistry()
        self._register_tools()

    def _register_tools(self) -> None:
        """把所有工具定义与处理函数注册进统一注册中心。"""
        handlers = {
            "query_recent_runtime_data": self.query_recent_runtime_data,
            "query_runtime_history": self.query_runtime_history,
            "query_latest_results": self.query_latest_results,
            "query_config_snapshot": self.query_config_snapshot,
            "query_config_pool": self.query_config_pool,
            "query_experience_pool": self.query_experience_pool,
            "generate_single_intersection_signal_timing": self.generate_single_intersection_signal_timing,
        }
        actions = {
            "query_recent_runtime_data": "runtime.recent",
            "query_runtime_history": "runtime.history",
            "query_latest_results": "results.latest",
            "query_config_snapshot": "config.snapshot",
            "generate_single_intersection_signal_timing": "signal.timing.single",
        }
        for spec in self._TOOL_SCHEMAS:
            self.registry.register(
                name=spec["name"],
                description=spec["description"],
                parameters=spec["parameters"],
                handler=handlers[spec["name"]],
                action=actions.get(spec["name"]),
            )

    def actions(self) -> dict[str, str]:
        """返回符号路由动作名到工具名的映射。"""
        return self.registry.actions()

    def tool_schemas(self) -> list[dict[str, Any]]:
        """返回可交给 Qwen 或其他工具调用框架的工具定义。"""
        return self.registry.tool_schemas()

    def invoke(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """按工具名称调用，供模型工具调用适配层使用。"""
        if name not in self.registry:
            return self._error(f"unknown tool: {name}")
        try:
            return self.registry.invoke(name, arguments)
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

    def query_config_pool(
        self,
        namespace: str | None = None,
        key: str | None = None,
        detail: str = SUMMARY,
    ) -> dict[str, Any]:
        """查询长期记忆中的持久化配置池。"""
        try:
            data = self.query_service.get_config_pool(key=key, namespace=namespace)
            normalized_detail = self._detail(detail)
            if isinstance(data, list):
                formatted = self._format_config_pool_records(data, normalized_detail)
                count = len(data)
            else:
                formatted = data if normalized_detail == self.FULL else self._format_config(data, normalized_detail)
                count = 0 if data is None else 1
            return self._success(
                f"已获取 {count} 条配置池数据。",
                formatted,
                {
                    "namespace": namespace,
                    "key": key,
                    "source": "config_pool",
                    "detail": normalized_detail,
                },
            )
        except (ValueError, RuntimeError) as error:
            return self._error(str(error))

    def query_experience_pool(
        self,
        category: str | None = None,
        key: str | None = None,
        limit: int = DEFAULT_LIMIT,
        detail: str = SUMMARY,
    ) -> dict[str, Any]:
        """查询长期记忆中的经验池。"""
        try:
            data = self.query_service.get_experience(key=key, category=category)
            normalized_detail = self._detail(detail)
            if isinstance(data, list):
                data = data[-self._limit(limit):]
                formatted = self._format_experience_records(data, normalized_detail)
                count = len(data)
            else:
                formatted = data if normalized_detail == self.FULL else self._format_config(data, normalized_detail)
                count = 0 if data is None else 1
            return self._success(
                f"已获取 {count} 条经验池数据。",
                formatted,
                {
                    "category": category,
                    "key": key,
                    "source": "experience_pool",
                    "detail": normalized_detail,
                },
            )
        except (ValueError, RuntimeError) as error:
            return self._error(str(error))

    def generate_single_intersection_signal_timing(
        self,
        cross_id: str,
        **context: Any,
    ) -> dict[str, Any]:
        """调用既有 DQN_Select 算法生成单路口放行时间。"""
        if self.signal_timing_tool is None:
            return self._error("signal timing tool is not configured")
        try:
            result = self.signal_timing_tool.generate(cross_id=cross_id, **context)
            return self._success(
                f"已生成路口 {cross_id} 的放行时间。",
                result,
                {"cross_id": cross_id, "source": "lib.DQN_Select.DQN_select"},
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

    @classmethod
    def _format_experience_records(cls, records: list[dict[str, Any]], detail: str) -> Any:
        if detail == cls.FULL:
            return records
        return {
            "count": len(records),
            "items": [
                {
                    "key": record.get("key"),
                    "category": record.get("category"),
                    "updated_at": record.get("updated_at"),
                    "value_fields": sorted(record.get("value", {}).keys()) if isinstance(record.get("value"), Mapping) else [],
                }
                for record in records
            ],
        }

    @classmethod
    def _format_config_pool_records(cls, records: list[dict[str, Any]], detail: str) -> Any:
        if detail == cls.FULL:
            return records
        return {
            "count": len(records),
            "items": [
                {
                    "key": record.get("key"),
                    "namespace": record.get("namespace"),
                    "updated_at": record.get("updated_at"),
                    "value_fields": sorted(record.get("value", {}).keys()) if isinstance(record.get("value"), Mapping) else [],
                }
                for record in records
            ],
        }

    @staticmethod
    def _success(summary: str, data: Any, meta: dict[str, Any]) -> dict[str, Any]:
        return ToolResponse.ok(summary, data, meta).to_dict()

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return ToolResponse.error(message).to_dict()
