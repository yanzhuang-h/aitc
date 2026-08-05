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
    """运行数据统一处理管线。

    socket 和 HTTP 服务仍负责协议层解析；进入本类后统一执行：
    ingest -> classify -> persist -> cache/state update。
    """

    def __init__(
        self,
        cache: RuntimeDataCache | None = None,
        writer: RuntimeDataWriter | None = None,
        lambdas_module: Any | None = None,
        overflow_warning_map: dict[str, Any] | None = None,
        radar_event_map: dict[str, Any] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.cache = cache or RuntimeDataCache()
        self.writer = writer or RuntimeDataWriter()
        self.lambdas = lambdas_module
        self.overflow_warning_map = overflow_warning_map
        self.radar_event_map = radar_event_map
        self.logger = logger

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
        self.writer.write(classified.kind, classified.item)
        return classified

    def _update_runtime_state(self, classified: ClassifiedData) -> None:
        data = classified.item

        if classified.kind == DataKind.FLOW:
            self.cache.add(DataKind.FLOW, data)
        elif classified.kind == DataKind.QUEUE:
            self.cache.add(DataKind.QUEUE, data)
        elif classified.kind == DataKind.STAGE:
            self.cache.add(DataKind.STAGE, data)
        elif classified.kind == DataKind.HEARTBEAT:
            self._debug("Heartbeat data")
        elif classified.kind == DataKind.ONLINE:
            if self._contains("online_data_map_lambda", data.get("rid")):
                self.cache.add(DataKind.ONLINE, data)
        elif classified.kind == DataKind.LATEST:
            if self._contains("latest_data_map_lambda", data.get("inter_id")):
                self.cache.add(DataKind.LATEST, data)
        elif classified.kind == DataKind.EXTEND:
            if self._contains("intersection_list", data.get("CrossId")):
                self.cache.add(DataKind.EXTEND, data)
        elif classified.kind == DataKind.OVERFLOW_WARNING:
            self._handle_overflow_warning(data)
        elif classified.kind == DataKind.RADAR:
            device_no = data.get("deviceNo")
            if self._contains("device_to_location", device_no):
                self.cache.add(DataKind.RADAR, data)
            self._debug(f"Processed radar data from device: {device_no}")
        elif classified.kind == DataKind.RADAR_EVENT:
            self._handle_radar_event(data)
        elif classified.kind == DataKind.BOYAN:
            device_id = data.get("deviceId")
            if self._contains("boyan_device_to_location", device_id):
                self.cache.add(DataKind.BOYAN, data)
        elif classified.source == DataSource.HTTP:
            self._warning("Received non-radar data in radar HTTP handler")
        else:
            self._info("Historical data")

    def _handle_overflow_warning(self, data: dict[str, Any]) -> None:
        self._info("Overflow warning data")
        try:
            ddbh = int(data.get("jtll_ddbh"))
        except (TypeError, ValueError):
            self._warning(f"Invalid overflow warning ddbh: {data.get('jtll_ddbh')}")
            return

        self._info(f"Overflow warning for ddbh: {ddbh}")
        location_map = self._get_lambdas_attr("location_to_intersection_lambda", {})
        if ddbh not in location_map or self.overflow_warning_map is None:
            return

        intersection_id, direction = location_map[ddbh]
        self._info(f"Intersection ID: {intersection_id}, Direction: {direction}")
        self.overflow_warning_map[intersection_id][direction] = data

    def _handle_radar_event(self, data: dict[str, Any]) -> None:
        type_value = data.get("eventType")
        device_no = data.get("deviceNo")
        radar_event_list = self._get_lambdas_attr("radar_event_list", [])
        if (
            type_value in radar_event_list
            and self._contains("device_to_location", device_no)
            and self.radar_event_map is not None
        ):
            self.radar_event_map[type_value][device_no] = data
        self._debug(f"Processed radar event from device: {device_no}")

    def _contains(self, attr_name: str, key: Any) -> bool:
        value = self._get_lambdas_attr(attr_name, None)
        return value is not None and key in value

    def _get_lambdas_attr(self, attr_name: str, default: Any) -> Any:
        if self.lambdas is None:
            return default
        return getattr(self.lambdas, attr_name, default)

    def _debug(self, message: str) -> None:
        if self.logger is not None:
            self.logger.debug(message)

    def _info(self, message: str) -> None:
        if self.logger is not None:
            self.logger.info(message)

    def _warning(self, message: str) -> None:
        if self.logger is not None:
            self.logger.warning(message)
