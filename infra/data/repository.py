"""Repository classes for traffic, config, and experience data."""

from __future__ import annotations

from datetime import datetime, timezone
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

    def __init__(self, store: JsonFileStore, max_records_per_kind: int = 10000) -> None:
        if max_records_per_kind <= 0:
            raise ValueError("max_records_per_kind must be positive")
        self.store = store
        self.max_records_per_kind = max_records_per_kind
        self._lock = threading.RLock()
        self._record_counts: dict[str, int] = {}

    def add(
        self,
        kind: DataKind | str,
        payload: Mapping[str, Any],
        source: DataSource | str = DataSource.UNKNOWN,
        intersection_id: str | None = None,
        received_at: str | None = None,
    ) -> dict[str, Any]:
        kind_name = kind.value if isinstance(kind, DataKind) else str(kind)
        source_name = source.value if isinstance(source, DataSource) else str(source)
        record = RuntimeRecord(
            kind=kind_name,
            payload=dict(payload),
            intersection_id=self._normalize_intersection_id(intersection_id),
            source=source_name,
            received_at=self._normalize_timestamp(received_at or utc_now_iso()),
        ).to_dict()
        with self._lock:
            name = f"runtime/{kind_name}.jsonl"
            self.store.append_jsonl(name, record)
            count = self._record_counts.get(kind_name)
            if count is None:
                count = len(self.store.read_jsonl(name))
            else:
                count += 1
            if count > self.max_records_per_kind:
                records = self.store.read_jsonl(name)[-self.max_records_per_kind:]
                self.store.write_jsonl(name, records)
                count = len(records)
            self._record_counts[kind_name] = count
        return record

    def latest(self, kind: DataKind | str) -> dict[str, Any] | None:
        records = self.window(kind, limit=1)
        return records[-1] if records else None

    def window(
        self,
        kind: DataKind | str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.query(kind, limit=limit)

    def query(
        self,
        kind: DataKind | str,
        limit: int = 100,
        intersection_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> list[dict[str, Any]]:
        """按路口和接收时间范围查询已持久化的运行记录。"""
        kind_name = kind.value if isinstance(kind, DataKind) else str(kind)
        start_time = self._parse_timestamp(start_at) if start_at else None
        end_time = self._parse_timestamp(end_at) if end_at else None
        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("start_at must not be after end_at")
        with self._lock:
            records = self.store.read_jsonl(f"runtime/{kind_name}.jsonl")
        filtered = []
        for record in records:
            if intersection_id is not None and record.get("intersection_id") != str(intersection_id):
                continue
            received_at = self._parse_timestamp(record["received_at"])
            if start_time is not None and received_at < start_time:
                continue
            if end_time is not None and received_at > end_time:
                continue
            filtered.append(record)
        return filtered[-limit:] if limit > 0 else []

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _normalize_timestamp(cls, value: str) -> str:
        try:
            parsed = cls._parse_timestamp(value)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("received_at must be an ISO 8601 timestamp") from error
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _normalize_intersection_id(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class KeyValueRepository:
    """JSON-backed key-value repository for configs and experience items."""

    def __init__(self, store: JsonFileStore, filename: str) -> None:
        self.store = store
        self.filename = filename

    def all(self) -> dict[str, Any]:
        return dict(self.store.read_json(self.filename, {}))

    def get(self, storage_key: str, default: Any = None) -> Any:
        return self.all().get(storage_key, default)

    def values(self, prefix: str | None = None) -> list[Any]:
        data = self.all()
        if prefix is None:
            return list(data.values())
        return [value for key, value in data.items() if key.startswith(prefix)]

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

    def list(self, namespace: str | None = None) -> list[dict[str, Any]]:
        prefix = f"{namespace}:" if namespace is not None else None
        return self.items.values(prefix=prefix)


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

    def list(self, category: str | None = None) -> list[dict[str, Any]]:
        prefix = f"{category}:" if category is not None else None
        return self.items.values(prefix=prefix)


class DataFoundationRepository:
    """Aggregate repository for the current data foundation."""

    def __init__(
        self,
        root: str | Path = "infra/data/runtime",
        cache_size: int = 100,
        runtime_max_records_per_kind: int = 10000,
    ) -> None:
        self.root = Path(root)
        self.store = JsonFileStore(self.root)
        self.traffic = TrafficRepository(self.store, cache_size=cache_size)
        self.runtime = RuntimeRepository(
            self.store,
            max_records_per_kind=runtime_max_records_per_kind,
        )
        self.config = ConfigRepository(self.store)
        self.experience = ExperienceRepository(self.store)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "root": str(self.root),
            "timestamp": utc_now_iso(),
        }
