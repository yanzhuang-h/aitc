"""协议接入后的统一数据入口。"""

from __future__ import annotations

from typing import Any, Mapping

from .classifier import ClassifiedData, DataSource
from .receiver import RuntimeDataReceiver


class RuntimeDataIngestor:
    """区分协议来源，并把数据送入统一运行数据管线。"""

    def __init__(self, receiver: RuntimeDataReceiver) -> None:
        self.receiver = receiver

    def ingest_tcp(
        self,
        payload: Mapping[str, Any] | list[Mapping[str, Any]],
    ) -> list[ClassifiedData]:
        return self._ingest_payload(payload, source=DataSource.TCP)

    def ingest_http(
        self,
        payload: Mapping[str, Any] | list[Mapping[str, Any]],
    ) -> list[ClassifiedData]:
        return self._ingest_payload(payload, source=DataSource.HTTP)

    def ingest_tcp_item(self, item: Mapping[str, Any]) -> ClassifiedData:
        return self.receiver.receive(item, source=DataSource.TCP)

    def ingest_http_item(self, item: Mapping[str, Any]) -> ClassifiedData:
        return self.receiver.receive(item, source=DataSource.HTTP)

    def _ingest_payload(
        self,
        payload: Mapping[str, Any] | list[Mapping[str, Any]],
        source: DataSource,
    ) -> list[ClassifiedData]:
        if isinstance(payload, list):
            return [self.receiver.receive(item, source=source) for item in payload]
        return [self.receiver.receive(payload, source=source)]
