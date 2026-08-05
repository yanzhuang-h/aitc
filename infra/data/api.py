"""Public API for the AITC data foundation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .repository import DataFoundationRepository
from .schemas import TrafficRecord


class DataRepository:
    """Facade used by agents and legacy code to access data foundation features."""

    def __init__(self, root: str | Path = "infra/data/runtime", cache_size: int = 100) -> None:
        self.repository = DataFoundationRepository(root=root, cache_size=cache_size)

    def health(self) -> dict[str, Any]:
        return self.repository.health()

    def receive_traffic(self, record: TrafficRecord | Mapping[str, Any]) -> dict[str, Any]:
        return self.repository.traffic.add(record)

    def get_latest_traffic(self, intersection_id: str) -> dict[str, Any] | None:
        return self.repository.traffic.latest(intersection_id)

    def get_traffic_window(self, intersection_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.traffic.window(intersection_id, limit=limit)

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


@lru_cache(maxsize=1)
def get_default_repository() -> DataRepository:
    return DataRepository()
