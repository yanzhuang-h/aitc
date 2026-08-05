"""Repository classes for traffic, config, and experience data."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Mapping

from .cache import WindowCache
from .classifier import DataKind, DataSource
from .schemas import ConfigItem, ExperienceItem, RuntimeRecord, TrafficRecord, utc_now_iso
from .storage import JsonFileStore


class TrafficRepository:
    """Store received traffic records and keep recent windows in memory."""

    def __init__(self, store: JsonFileStore, cache_size: int = 100) -> None:
        self.store = store
        self.cache: WindowCache[dict[str, Any]] = WindowCache(max_size=cache_size)

    def add(self, record: TrafficRecord | Mapping[str, Any]) -> dict[str, Any]:
        traffic_record = (
            record if isinstance(record, TrafficRecord) else TrafficRecord.from_mapping(record)
        )
        data = traffic_record.to_dict()
        self.cache.append(traffic_record.intersection_id, data)
        self.store.append_jsonl(
            f"traffic/{traffic_record.intersection_id}.jsonl",
            data,
        )
        return data

    def latest(self, intersection_id: str) -> dict[str, Any] | None:
        cached = self.cache.latest(intersection_id)
        if cached is not None:
            return cached
        records = self.store.read_jsonl(f"traffic/{intersection_id}.jsonl")
        return records[-1] if records else None

    def window(self, intersection_id: str, limit: int = 20) -> list[dict[str, Any]]:
        cached = self.cache.window(intersection_id, limit)
        if cached:
            return cached
        records = self.store.read_jsonl(f"traffic/{intersection_id}.jsonl")
        return records[-limit:] if limit > 0 else []


class RuntimeRepository:
    """按数据类型持久化运行时接入记录。"""

    def __init__(self, store: JsonFileStore) -> None:
        self.store = store
        self._lock = threading.RLock()

    def add(
        self,
        kind: DataKind | str,
        payload: Mapping[str, Any],
        source: DataSource | str = DataSource.UNKNOWN,
    ) -> dict[str, Any]:
        kind_name = kind.value if isinstance(kind, DataKind) else str(kind)
        source_name = source.value if isinstance(source, DataSource) else str(source)
        record = RuntimeRecord(
            kind=kind_name,
            payload=dict(payload),
            source=source_name,
        ).to_dict()
        with self._lock:
            self.store.append_jsonl(f"runtime/{kind_name}.jsonl", record)
        return record

    def latest(self, kind: DataKind | str) -> dict[str, Any] | None:
        records = self.window(kind, limit=1)
        return records[-1] if records else None

    def window(
        self,
        kind: DataKind | str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        kind_name = kind.value if isinstance(kind, DataKind) else str(kind)
        with self._lock:
            records = self.store.read_jsonl(f"runtime/{kind_name}.jsonl")
        return records[-limit:] if limit > 0 else []


class KeyValueRepository:
    """JSON-backed key-value repository for configs and experience items."""

    def __init__(self, store: JsonFileStore, filename: str) -> None:
        self.store = store
        self.filename = filename

    def all(self) -> dict[str, Any]:
        return dict(self.store.read_json(self.filename, {}))

    def get(self, storage_key: str, default: Any = None) -> Any:
        return self.all().get(storage_key, default)

    def set(self, storage_key: str, value: Any) -> Any:
        data = self.all()
        data[storage_key] = value
        self.store.write_json(self.filename, data)
        return value


class ConfigRepository:
    """Persist and query configuration items."""

    def __init__(self, store: JsonFileStore) -> None:
        self.items = KeyValueRepository(store, "config/items.json")

    def set(self, key: str, value: Any, namespace: str = "default") -> dict[str, Any]:
        item = ConfigItem(key=key, value=value, namespace=namespace)
        self.items.set(item.storage_key(), item.to_dict())
        return item.to_dict()

    def get(self, key: str, namespace: str = "default", default: Any = None) -> Any:
        item = self.items.get(f"{namespace}:{key}")
        if item is None:
            return default
        return item.get("value", default)


class ExperienceRepository:
    """Persist and query experience-pool items."""

    def __init__(self, store: JsonFileStore) -> None:
        self.items = KeyValueRepository(store, "experience/items.json")

    def set(self, key: str, value: dict[str, Any], category: str = "default") -> dict[str, Any]:
        item = ExperienceItem(key=key, value=value, category=category)
        self.items.set(item.storage_key(), item.to_dict())
        return item.to_dict()

    def get(
        self,
        key: str,
        category: str = "default",
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        item = self.items.get(f"{category}:{key}")
        if item is None:
            return default
        return item.get("value", default)


class DataFoundationRepository:
    """Aggregate repository for the current data foundation."""

    def __init__(self, root: str | Path = "infra/data/runtime", cache_size: int = 100) -> None:
        self.root = Path(root)
        self.store = JsonFileStore(self.root)
        self.traffic = TrafficRepository(self.store, cache_size=cache_size)
        self.runtime = RuntimeRepository(self.store)
        self.config = ConfigRepository(self.store)
        self.experience = ExperienceRepository(self.store)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "root": str(self.root),
            "timestamp": utc_now_iso(),
        }
