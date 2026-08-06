"""长短期记忆的统一查询层。"""

from __future__ import annotations

import copy
from typing import Any

from ..classifier import DataKind
from ..config import ConfigResource, ConfigService
from .long_term import LongTermMemory
from ..quality import DataQualityMonitor
from ..result_warehouse import ResultWarehouse
from .short_term import ShortTermMemory


class MemoryQueryLayer:
    """为运行模块和 Agent 提供统一的只读查询入口。"""

    def __init__(
        self,
        short_term_memory: ShortTermMemory | None = None,
        result_warehouse: ResultWarehouse | None = None,
        config_service: ConfigService | None = None,
        long_term_memory: LongTermMemory | None = None,
        quality_monitor: DataQualityMonitor | None = None,
    ) -> None:
        self._short_term_memory = short_term_memory
        self._long_term_memory = long_term_memory
        if self._short_term_memory is None or result_warehouse is None or config_service is None:
            raise TypeError("short_term_memory, result_warehouse and config_service are required")
        self._result_warehouse = result_warehouse
        self._config_service = config_service
        self._quality_monitor = quality_monitor

    def get_data_quality_snapshot(self) -> dict[str, Any]:
        return self._quality_monitor.snapshot() if self._quality_monitor is not None else {
            "total_issues": 0,
            "issues_by_kind": {},
            "recent_issues": [],
        }

    def get_runtime_data(self, kind: DataKind | str, limit: int | None = None) -> list[dict[str, Any]]:
        data_kind = self._data_kind(kind)
        records = self._short_term_memory.recent_data(data_kind)
        if limit is not None:
            records = records[-max(0, limit):]
        return copy.deepcopy(records)

    def get_runtime_size(self, kind: DataKind | str) -> int:
        return self._short_term_memory.size(self._data_kind(kind))

    def get_runtime_history(
        self,
        kind: DataKind | str,
        limit: int = 100,
        intersection_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._long_term_memory is None:
            raise RuntimeError("long-term memory is not configured")
        return self._long_term_memory.get_runtime_history(
            self._data_kind(kind), limit, intersection_id, start_at, end_at
        )

    def get_runtime_snapshot(self, limit_per_kind: int | None = None) -> dict[str, list[dict[str, Any]]]:
        return {
            kind.value: self.get_runtime_data(kind, limit=limit_per_kind)
            for kind in self._short_term_memory.windows
        }

    def get_latest_results(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._result_warehouse.snapshot())

    def get_experience(
        self,
        key: str | None = None,
        category: str | None = None,
    ) -> Any:
        if self._long_term_memory is None:
            raise RuntimeError("long-term memory is not configured")
        if key is not None:
            return copy.deepcopy(self._long_term_memory.get_experience(key, category or "default"))
        return copy.deepcopy(self._long_term_memory.list_experience(category=category))

    def get_config_snapshot(self, resource: ConfigResource | str, cross_id: str | None = None) -> Any:
        config_resource = ConfigResource(resource)
        if config_resource in {ConfigResource.ROAD_INFO, ConfigResource.CROSS_INFO}:
            if cross_id is None:
                raise ValueError(f"cross_id is required for {config_resource.value}")
            return self._config_service.query(config_resource, cross_id)
        if config_resource == ConfigResource.ROAD_STATE:
            return self._config_service.get_road_state()
        if config_resource == ConfigResource.FLOATING_VALUE:
            return self._config_service.get_floating_value()
        if config_resource == ConfigResource.INTERSECTION_RESULT:
            return self._config_service.get_intersection_result_config()
        if config_resource == ConfigResource.TIME_SCHEDULE:
            return self._config_service.get_time_schedule_manifest() if cross_id is None else self._config_service.get_time_schedule(cross_id)
        raise ValueError(f"unsupported config resource: {config_resource}")

    @staticmethod
    def _data_kind(kind: DataKind | str) -> DataKind:
        if isinstance(kind, DataKind):
            return kind
        try:
            return DataKind(kind)
        except ValueError as error:
            raise ValueError(f"unsupported data kind: {kind}") from error
