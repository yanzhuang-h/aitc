"""长期记忆仓库。

长期记忆负责保存可追溯的运行历史，以及配置和经验数据。它只定义访问
语义，当前默认使用 JSON/JSONL 文件实现，后续可以替换为数据库或其他
持久化技术。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .classifier import DataKind
from .repository import DataFoundationRepository
from .schemas import TrafficRecord


class LongTermMemory:
    """面向长期保存的数据仓库门面。"""

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
        """保存一条已分类的运行记录。"""
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
