"""数据生产方接收辅助组件。"""

from __future__ import annotations

from typing import Any, Mapping

from .classifier import ClassifiedData, DataKind, DataSource, classify_data
from .datahub import TrafficDataHub
from .contracts import validate_contract
from .quality import DataQualityMonitor
from .memory.short_term import ShortTermMemory
from .writer import RuntimeDataWriter
from infra.logging import LoggingMixin


class RuntimeDataReceiver(LoggingMixin):
    """运行数据统一处理管线。

    socket 和 HTTP 服务仍负责协议层解析；进入本类后统一执行：
    ingest -> classify -> persist -> cache/state update。
    """

    def __init__(
        self,
        cache: ShortTermMemory | None = None,
        writer: RuntimeDataWriter | None = None,
        repository: LongTermMemory | None = None,
        lambdas_module: Any | None = None,
        overflow_warning_map: dict[str, Any] | None = None,
        radar_event_map: dict[str, Any] | None = None,
        logger: Any | None = None,
        quality_monitor: DataQualityMonitor | None = None,
        datahub: TrafficDataHub | None = None,
    ) -> None:
        if datahub is not None and cache is not None and cache is not datahub.cache:
            raise ValueError("receiver cache must be the DataHub cache")
        self.datahub = datahub if datahub is not None else TrafficDataHub(
            cache=cache, lambdas_module=lambdas_module,
            overflow_warning_map=overflow_warning_map, radar_event_map=radar_event_map,
            logger=logger,
        )
        self.cache = self.datahub.cache
        self.writer = writer or RuntimeDataWriter()
        self.repository = repository
        self.lambdas = self.datahub.lambdas
        self.overflow_warning_map = self.datahub.overflow_warning_map
        self.radar_event_map = self.datahub.radar_event_map
        self.logger = logger
        self.quality_monitor = quality_monitor or DataQualityMonitor()

    def receive(
        self,
        item: Mapping[str, Any],
        source: DataSource | str = DataSource.UNKNOWN,
    ) -> ClassifiedData:
        classified = self._classify_and_persist(item, source)
        self._update_runtime_state(classified)
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

    def receive_tcp(self, item: Mapping[str, Any]) -> ClassifiedData:
        return self.receive(item, source=DataSource.TCP)

    def receive_http(self, item: Mapping[str, Any]) -> ClassifiedData:
        return self.receive(item, source=DataSource.HTTP)

    def _classify_and_persist(
        self,
        item: Mapping[str, Any],
        source: DataSource | str,
    ) -> ClassifiedData:
        classified = classify_data(item, source=source)
        self.quality_monitor.record(
            classified.kind,
            classified.source,
            validate_contract(classified.kind, classified.item, classified.source),
        )
        self.writer.write(classified.kind, classified.item)
        if self.repository is not None:
            self.repository.store_runtime_data(
                classified.kind,
                classified.item,
                source=classified.source.value,
                intersection_id=self._resolve_intersection_id(classified.item),
            )
        return classified

    def _update_runtime_state(self, classified: ClassifiedData) -> None:
        self.datahub.ingest_classified(classified)

    def _resolve_intersection_id(self, data: Mapping[str, Any]) -> str | None:
        for key in ("Cross_id", "CrossId", "cross_id", "intersection_id", "inter_id"):
            value = data.get(key)
            if value is not None and str(value).strip():
                return str(value)

        try:
            detector_id = int(data.get("jtll_ddbh"))
        except (TypeError, ValueError):
            return None
        location_map = self._get_lambdas_attr("location_to_intersection_lambda", {})
        location = location_map.get(detector_id)
        return str(location[0]) if location else None

    def _get_lambdas_attr(self, attr_name: str, default: Any) -> Any:
        if self.lambdas is None:
            return default
        return getattr(self.lambdas, attr_name, default)
