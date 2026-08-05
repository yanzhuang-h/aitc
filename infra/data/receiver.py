"""数据生产方接收辅助组件。"""

from __future__ import annotations

from typing import Any, Mapping

from .api import DataRepository, get_default_repository
from .classifier import ClassifiedData, DataKind, DataSource, classify_data
from .runtime_cache import RuntimeDataCache
from .writer import RuntimeDataWriter


class TrafficReceiver:
    """接收外部生产方的交通数据。"""

    def __init__(self, repository: DataRepository | None = None) -> None:
        self.repository = repository or get_default_repository()

    def receive(
        self,
        intersection_id: str,
        payload: Mapping[str, Any],
        source: str = "unknown",
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "intersection_id": intersection_id,
            "payload": dict(payload),
            "source": source,
        }
        if timestamp is not None:
            record["timestamp"] = timestamp
        return self.repository.receive_traffic(record)


class RuntimeDataReceiver:
    """对运行数据执行分类、写入和缓存。

    该类刻意保持轻量：socket 和 HTTP 服务仍负责传输细节，这里只负责
    公共数据路径。
    """

    def __init__(
        self,
        cache: RuntimeDataCache | None = None,
        writer: RuntimeDataWriter | None = None,
    ) -> None:
        self.cache = cache or RuntimeDataCache()
        self.writer = writer or RuntimeDataWriter()

    def receive(
        self,
        item: Mapping[str, Any],
        source: DataSource | str = DataSource.UNKNOWN,
    ) -> ClassifiedData:
        classified = classify_data(item, source=source)
        self.writer.write(classified.kind, classified.item)
        self.cache.add(classified.kind, classified.item)
        return classified

    def receive_many(
        self,
        payload: Mapping[str, Any] | list[Mapping[str, Any]],
        source: DataSource | str = DataSource.UNKNOWN,
    ) -> list[ClassifiedData]:
        if isinstance(payload, list):
            return [self.receive(item, source=source) for item in payload]
        return [self.receive(payload, source=source)]

    def recent(self, kind: DataKind) -> list[dict[str, Any]]:
        return self.cache.recent_data(kind)
