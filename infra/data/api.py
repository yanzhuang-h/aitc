"""Public API for the AITC data foundation."""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .classifier import DataKind
from .config import ConfigResource, ConfigService
from .repository import DataFoundationRepository
from .result_warehouse import ResultWarehouse
from .runtime_cache import RuntimeDataCache
from .schemas import TrafficRecord


class DataRepository:
    """Facade used by agents and legacy code to access data foundation features."""

    def __init__(
        self,
        root: str | Path = "infra/data/runtime",
        cache_size: int = 100,
        runtime_max_records_per_kind: int = 10000,
    ) -> None:
        self.repository = DataFoundationRepository(
            root=root,
            cache_size=cache_size,
            runtime_max_records_per_kind=runtime_max_records_per_kind,
        )

    def health(self) -> dict[str, Any]:
        return self.repository.health()

    def receive_traffic(self, record: TrafficRecord | Mapping[str, Any]) -> dict[str, Any]:
        return self.repository.traffic.add(record)

    def get_latest_traffic(self, intersection_id: str) -> dict[str, Any] | None:
        return self.repository.traffic.latest(intersection_id)

    def get_traffic_window(self, intersection_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.traffic.window(intersection_id, limit=limit)

    def store_runtime_data(
        self,
        kind: DataKind | str,
        payload: Mapping[str, Any],
        source: str = "unknown",
        intersection_id: str | None = None,
        received_at: str | None = None,
    ) -> dict[str, Any]:
        """持久化一条已分类的运行数据。"""
        return self.repository.runtime.add(
            kind,
            payload,
            source=source,
            intersection_id=intersection_id,
            received_at=received_at,
        )

    def get_latest_runtime_data(self, kind: DataKind | str) -> dict[str, Any] | None:
        return self.repository.runtime.latest(kind)

    def get_runtime_history(
        self,
        kind: DataKind | str,
        limit: int = 100,
        intersection_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.repository.runtime.query(
            kind,
            limit=limit,
            intersection_id=intersection_id,
            start_at=start_at,
            end_at=end_at,
        )

    def set_config(self, key: str, value: Any, namespace: str = "default") -> dict[str, Any]:
        return self.repository.config.set(key=key, value=value, namespace=namespace)

    def get_config(self, key: str, namespace: str = "default", default: Any = None) -> Any:
        return self.repository.config.get(key=key, namespace=namespace, default=default)

    def set_experience(
        self,
        key: str,
        value: dict[str, Any],
        category: str = "default",
    ) -> dict[str, Any]:
        return self.repository.experience.set(key=key, value=value, category=category)

    def get_experience(
        self,
        key: str,
        category: str = "default",
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self.repository.experience.get(key=key, category=category, default=default)


class RuntimeDataQueryService:
    """运行态数据的统一只读查询入口。

    当前使用内存窗口、结果仓库和旧配置适配实现；调用方不需要了解底层
    缓存或配置文件。后续迁移 Redis、数据库时保持本接口不变。
    """

    def __init__(
        self,
        cache: RuntimeDataCache,
        result_warehouse: ResultWarehouse,
        config_service: ConfigService,
        repository: DataRepository | None = None,
    ) -> None:
        self.cache = cache
        self.result_warehouse = result_warehouse
        self.config_service = config_service
        self.repository = repository

    def get_runtime_data(
        self,
        kind: DataKind | str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """查询指定类型的近期运行数据快照。"""
        data_kind = self._data_kind(kind)
        records = self.cache.recent_data(data_kind)
        if limit is not None:
            records = records[-max(0, limit):]
        return copy.deepcopy(records)

    def get_runtime_size(self, kind: DataKind | str) -> int:
        """查询指定运行窗口中的有效数据数量。"""
        return self.cache.size(self._data_kind(kind))

    def get_runtime_history(
        self,
        kind: DataKind | str,
        limit: int = 100,
        intersection_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> list[dict[str, Any]]:
        """查询持久化的运行数据历史。"""
        if self.repository is None:
            raise RuntimeError("runtime repository is not configured")
        return self.repository.get_runtime_history(
            self._data_kind(kind),
            limit=limit,
            intersection_id=intersection_id,
            start_at=start_at,
            end_at=end_at,
        )

    def get_runtime_snapshot(
        self,
        limit_per_kind: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """查询全部运行窗口的快照。"""
        return {
            kind.value: self.get_runtime_data(kind, limit=limit_per_kind)
            for kind in self.cache.windows
        }

    def get_latest_results(self) -> list[dict[str, Any]]:
        """查询当前可发送的最新路口决策结果。"""
        return copy.deepcopy(self.result_warehouse.snapshot())

    def get_config_snapshot(
        self,
        resource: ConfigResource | str,
        cross_id: str | None = None,
    ) -> Any:
        """按资源读取配置快照。路口级配置需要传入 cross_id。"""
        config_resource = ConfigResource(resource)
        if config_resource in {
            ConfigResource.ROAD_INFO,
            ConfigResource.CROSS_INFO,
        }:
            if cross_id is None:
                raise ValueError(f"cross_id is required for {config_resource.value}")
            return self.config_service.query(config_resource, cross_id)
        if config_resource == ConfigResource.ROAD_STATE:
            return self.config_service.get_road_state()
        if config_resource == ConfigResource.FLOATING_VALUE:
            return self.config_service.get_floating_value()
        if config_resource == ConfigResource.INTERSECTION_RESULT:
            return self.config_service.get_intersection_result_config()
        if config_resource == ConfigResource.TIME_SCHEDULE:
            if cross_id is None:
                return self.config_service.get_time_schedule_manifest()
            return self.config_service.get_time_schedule(cross_id)
        raise ValueError(f"unsupported config resource: {config_resource}")

    @staticmethod
    def _data_kind(kind: DataKind | str) -> DataKind:
        if isinstance(kind, DataKind):
            return kind
        try:
            return DataKind(kind)
        except ValueError as error:
            raise ValueError(f"unsupported data kind: {kind}") from error


@lru_cache(maxsize=1)
def get_default_repository() -> DataRepository:
    return DataRepository()
