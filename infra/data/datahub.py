"""唯一运行交通状态入口；保留旧时间窗口，新增按路口的有界查询与轮次历史。"""

from __future__ import annotations

import copy
import threading
import time
from collections import deque
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.config import DEFAULT_DATAHUB_EVENT_LIMIT, DEFAULT_MEMORY_WINDOW
from infra.logging import LoggingMixin
from lib.control_functions.types import IntersectionControlRequest

from .classifier import ClassifiedData, DataKind, DataSource, classify_data
from .contracts import CONTRACTS, validate_contract
from .memory.short_term import ShortTermMemory
from .traffic_adapters import snapshot_from_legacy
from .traffic_schemas import RawTrafficEvent, TrafficDataView, TrafficSnapshot, TrafficSource


SOURCE_KINDS: dict[TrafficSource, frozenset[DataKind]] = {
    "video": frozenset((DataKind.FLOW, DataKind.QUEUE, DataKind.STAGE,
                        DataKind.EXTEND, DataKind.OVERFLOW_WARNING)),
    "radar": frozenset((DataKind.RADAR, DataKind.RADAR_EVENT, DataKind.BOYAN)),
    "internet": frozenset((DataKind.ONLINE, DataKind.LATEST)),
    "ev": frozenset(),
}


class TrafficDataHub(LoggingMixin):
    """接入和查询共享状态；所有 V2 输入/输出复制，旧缓存仍使用原报文。

    ingest 是严格 V2 边界，ingest_classified 是不新增过滤的生产兼容入口。
    capture 保存真正送入选择器的状态，不重新实现任何聚合算法。
    """

    def __init__(
        self, *, cache: ShortTermMemory | None = None,
        lambdas_module: Any | None = None,
        overflow_warning_map: dict[str, Any] | None = None,
        radar_event_map: dict[str, Any] | None = None,
        memory_window: int = DEFAULT_MEMORY_WINDOW,
        event_limit: int = DEFAULT_DATAHUB_EVENT_LIMIT,
        logger: Any | None = None,
    ) -> None:
        for name, value in (("memory_window", memory_window), ("event_limit", event_limit)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.cache = cache if cache is not None else ShortTermMemory()
        self.lambdas = lambdas_module
        self.overflow_warning_map = overflow_warning_map
        self.radar_event_map = radar_event_map
        self.memory_window = memory_window
        self.event_limit = event_limit
        self.logger = logger
        self._lock = threading.RLock()
        self._ingest_lock = threading.Lock()
        self._last_received_at: dict[DataKind, float] = {}
        self._events: dict[str | None, deque[RawTrafficEvent]] = {}
        self._history: dict[str, deque[TrafficSnapshot]] = {}
        self._snapshot_issues: dict[str | None, str] = {}
        self._event_issues: dict[str | None, tuple[str, float]] = {}
        self._truncated_until: dict[str | None, float] = {}
        self._next_event_cleanup = 0.0
        known_ids = self._get_lambdas_attr("intersection_list", None)
        self._known_ids = set(known_ids) if known_ids is not None else None
        # 一个互联网路段可服务多个路口，方向为 None 的关联也不能丢弃。
        self._rid_intersections: dict[Any, list[str]] = {}
        for intersection_id, roads in self._get_lambdas_attr("intersection_to_rid_lambda", {}).items():
            for rid, _direction in roads:
                ids = self._rid_intersections.setdefault(rid, [])
                resolved = self._canonical_id(intersection_id)
                if resolved is not None and resolved not in ids:
                    ids.append(resolved)

    def ingest(self, event: RawTrafficEvent) -> None:
        """校验信封及分类一致性，失败时不写入任何运行状态。"""
        validated = RawTrafficEvent.model_validate(event).model_copy(deep=True)
        classified = classify_data(validated.payload, validated.source)
        if classified.kind != validated.kind:
            raise ValueError("event.kind does not match legacy payload classification")
        validated.quality_issues = list(dict.fromkeys([
            *validated.quality_issues,
            *validate_contract(classified.kind, classified.item, classified.source),
        ]))
        prepared = self._prepare_events(validated)
        with self._ingest_lock:
            # 原窗口只从队首清理，严格入口不能向同一类型倒序插入接收时间。
            if validated.received_at > time.time():
                raise ValueError("received_at must not be in the future")
            if validated.received_at < self._last_received_at.get(validated.kind, -1):
                raise ValueError("received_at must be nondecreasing within each data kind")
            self._update_runtime_state(classified, timestamp=validated.received_at)
            self._last_received_at[validated.kind] = validated.received_at
            self._record_events(prepared)

    def ingest_classified(self, classified: ClassifiedData) -> None:
        """保持旧准入规则、原报文引用和接收时钟；质量信息只用于新查询。"""
        with self._ingest_lock:
            self._update_runtime_state(classified)
            received_at = time.time()
            self._last_received_at[classified.kind] = max(
                received_at, self._last_received_at.get(classified.kind, -1),
            )
            event = RawTrafficEvent(
                kind=classified.kind, source=classified.source, received_at=received_at,
                payload=classified.item,
                quality_issues=validate_contract(classified.kind, classified.item, classified.source),
            )
            try:
                prepared = self._prepare_events(event)
            except RecursionError as error:
                # 深层 vendor 报文可以被旧缓存接收，却超过 Python 复制深度。
                issue = f"event_capture_failed: {type(error).__name__}"
                expiry = received_at + self.cache.windows.get(classified.kind, 600)
                with self._lock:
                    for intersection_id in self._event_ids(event):
                        previous = self._event_issues.get(intersection_id)
                        self._event_issues[intersection_id] = (
                            issue, max(expiry, previous[1]) if previous else expiry,
                        )
                self._warning("DataHub event capture failed: %s", error)
                return
            self._record_events(prepared)

    def capture(self, request: IntersectionControlRequest) -> TrafficSnapshot | None:
        """选择器运行前保存单路口输入；严格契约不通过则记录质量问题。"""
        partition = request.cross_id if isinstance(request.cross_id, str) else None
        if self._known_ids is not None and partition not in self._known_ids:
            with self._lock:
                self._snapshot_issues[None] = "snapshot_intersection_unresolved"
            self._warning("DataHub snapshot intersection is unknown: %s", request.cross_id)
            return None
        try:
            snapshot = snapshot_from_legacy(request)
            returned = copy.deepcopy(snapshot)
        except (ValidationError, RecursionError) as error:
            reason = "snapshot_validation_failed" if isinstance(error, ValidationError) else "snapshot_capture_failed"
            issue = f"{reason}: {type(error).__name__}: {error}"
            with self._lock:
                self._snapshot_issues[partition] = issue
            self._warning("DataHub snapshot capture failed for %s: %s", request.cross_id, error)
            return None
        with self._lock:
            self._history.setdefault(snapshot.cross_id, deque(maxlen=self.memory_window)).append(snapshot)
            self._snapshot_issues.pop(snapshot.cross_id, None)
        return returned

    def latest(self, intersection_id: str) -> TrafficSnapshot | None:
        intersection_id = self._validated_id(intersection_id)
        with self._lock:
            history = self._history.get(intersection_id)
            return copy.deepcopy(history[-1]) if history else None

    def history(self, intersection_id: str, limit: int | None = None) -> list[TrafficSnapshot]:
        """按最旧到最新返回最近 N 轮，包含当前轮；limit 取末尾若干轮。"""
        intersection_id = self._validated_id(intersection_id)
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("limit must be a nonnegative integer")
        with self._lock:
            snapshots = list(self._history.get(intersection_id, ()))
            if limit is not None:
                snapshots = snapshots[-limit:] if limit else []
            return copy.deepcopy(snapshots)

    def clear_expired(self) -> None:
        """决策轮清理原缓存，并释放全部过期事件分区。"""
        self.cache.clear_expired()
        with self._lock:
            self._clear_expired_events(time.time(), force=True)

    def query(
        self, intersection_id: str | None, source: TrafficSource | None = None,
        *, transport: DataSource | None = None, kind: DataKind | None = None,
    ) -> TrafficDataView:
        """读取当前事件窗口和完整决策上下文；None 查询未关联事件。"""
        if intersection_id is not None:
            intersection_id = self._validated_id(intersection_id)
        source = TypeAdapter(TrafficSource | None).validate_python(source, strict=True)
        if transport is not None:
            transport = DataSource(transport)
        if kind is not None:
            kind = DataKind(kind)
        now = time.time()
        with self._lock:
            self._clear_expired_events(now)
            self._prune_events(intersection_id, now)
            events = [event for event in self._events.get(intersection_id, ())
                      if (source is None or event.kind in SOURCE_KINDS[source])
                      and (transport is None or event.source == transport)
                      and (kind is None or event.kind == kind)]
            history = self._history.get(intersection_id)
            snapshot = history[-1] if history else None
            missing = []
            if not events:
                missing.append("events")
            if snapshot is None:
                missing.append("snapshot")
            kinds = {event.kind for event in events}
            if source == "video":
                missing.extend(k.value for k in (DataKind.FLOW, DataKind.QUEUE) if k not in kinds)
            elif source == "radar" and not kinds.intersection((DataKind.RADAR, DataKind.BOYAN)):
                missing.append("radar_observation")
            elif source == "internet" and DataKind.ONLINE not in kinds:
                missing.append("online")
            elif source == "ev":
                missing.append("ev")
            issues = [issue for event in events for issue in event.quality_issues]
            if intersection_id in self._event_issues:
                missing.append("event_capture")
                issues.append(self._event_issues[intersection_id][0])
            for event in events:
                contract = CONTRACTS.get(event.kind)
                if contract is not None:
                    missing.extend(f"{event.kind.value}.{field}" for field in contract.required_fields
                                   if event.payload.get(field) is None)
            if intersection_id in self._snapshot_issues:
                missing.append("snapshot_current_round")
                issues.append(self._snapshot_issues[intersection_id])
            truncated = now <= self._truncated_until.get(intersection_id, -1)
            if truncated:
                issues.append("event_window_truncated")
            return TrafficDataView(
                intersection_id=intersection_id, source=source, transport=transport,
                events=copy.deepcopy(events), snapshot=copy.deepcopy(snapshot),
                missing_fields=list(dict.fromkeys(missing)),
                quality_issues=list(dict.fromkeys(issues)), truncated=truncated,
            )

    def _event_ids(self, event: RawTrafficEvent) -> list[str | None]:
        ids = ([self._canonical_id(event.intersection_id)] if event.intersection_id is not None
               else self._intersection_ids(event))
        if self._known_ids is not None:
            ids = [intersection_id for intersection_id in ids if intersection_id in self._known_ids]
        return ids or [None]

    def _prepare_events(self, event: RawTrafficEvent) -> list[RawTrafficEvent]:
        prepared = []
        for intersection_id in self._event_ids(event):
            stored = event.model_copy(deep=True, update={"intersection_id": intersection_id})
            if intersection_id is None:
                stored.quality_issues.append("intersection_unresolved")
            prepared.append(stored)
        return prepared

    def _record_events(self, prepared: list[RawTrafficEvent]) -> None:
        now = time.time()
        with self._lock:
            self._clear_expired_events(now)
            for stored in prepared:
                intersection_id = stored.intersection_id
                events = self._events.setdefault(intersection_id, deque(maxlen=self.event_limit))
                if len(events) == self.event_limit:
                    self._prune_events(intersection_id, now)
                    events = self._events.setdefault(intersection_id, deque(maxlen=self.event_limit))
                if len(events) == self.event_limit:
                    dropped = events[0]
                    expiry = dropped.received_at + self.cache.windows.get(dropped.kind, 600)
                    self._truncated_until[intersection_id] = max(
                        expiry, self._truncated_until.get(intersection_id, -1),
                    )
                events.append(stored)

    def _clear_expired_events(self, now: float, *, force: bool = False) -> None:
        if force or now >= self._next_event_cleanup:
            for intersection_id in set(self._events) | set(self._truncated_until) | set(self._event_issues):
                self._prune_events(intersection_id, now)
            self._next_event_cleanup = now + 30

    def _prune_events(self, intersection_id: str | None, now: float) -> None:
        events = self._events.get(intersection_id)
        if events is not None:
            active = [event for event in events
                      if now - event.received_at <= self.cache.windows.get(event.kind, 600)]
            events.clear()
            events.extend(active)
            if not events:
                self._events.pop(intersection_id, None)
        if now > self._truncated_until.get(intersection_id, -1):
            self._truncated_until.pop(intersection_id, None)
        issue = self._event_issues.get(intersection_id)
        if issue is not None and now > issue[1]:
            self._event_issues.pop(intersection_id, None)

    @staticmethod
    def _validated_id(intersection_id: str) -> str:
        if not isinstance(intersection_id, str) or not intersection_id.strip():
            raise ValueError("intersection_id must be a nonempty string")
        return intersection_id

    def _canonical_id(self, value: Any) -> str | None:
        if value is None or not str(value).strip():
            return None
        value = str(value)
        aliases = self._get_lambdas_attr("aibi_to_xinkongji", {})
        return str(aliases.get(value, value))

    def _intersection_ids(self, event: RawTrafficEvent) -> list[str | None]:
        data = event.payload
        for key in ("Cross_id", "CrossId", "cross_id", "intersection_id"):
            resolved = self._canonical_id(data.get(key))
            if resolved is not None:
                return [resolved]
        if event.kind == DataKind.ONLINE:
            return self._lookup(self._rid_intersections, data.get("rid")) or []
        if event.kind == DataKind.LATEST:
            resolved = self._canonical_id(data.get("inter_id"))
            # inter_id 通常为地图节点，不能凭名称视为信控路口。
            return [resolved] if resolved in self._get_lambdas_attr("intersection_list", []) else []
        if event.kind in (DataKind.RADAR, DataKind.RADAR_EVENT):
            location = self._lookup(self._get_lambdas_attr("device_to_location", {}), data.get("deviceNo"))
        elif event.kind == DataKind.BOYAN:
            location = self._lookup(self._get_lambdas_attr("boyan_device_to_location", {}), data.get("deviceId"))
        else:
            try:
                detector_id = int(data.get("jtll_ddbh"))
            except (TypeError, ValueError, OverflowError):
                return []
            location = self._get_lambdas_attr("location_to_intersection_lambda", {}).get(detector_id)
        return [self._canonical_id(location[0])] if location else []

    @staticmethod
    def _lookup(mapping: dict[Any, Any], key: Any) -> Any:
        # 旧链路在未配置映射时可忽略异构标识；质量索引不能新增 TypeError。
        try:
            return mapping.get(key)
        except TypeError:
            return None

    def _update_runtime_state(self, classified: ClassifiedData, timestamp: float | None = None) -> None:
        """从接收器移入的旧准入逻辑；不按质量或新路口索引过滤。"""
        data = classified.item

        if classified.kind == DataKind.FLOW:
            self.cache.add(DataKind.FLOW, data, timestamp=timestamp)
        elif classified.kind == DataKind.QUEUE:
            self.cache.add(DataKind.QUEUE, data, timestamp=timestamp)
        elif classified.kind == DataKind.STAGE:
            self.cache.add(DataKind.STAGE, data, timestamp=timestamp)
        elif classified.kind == DataKind.HEARTBEAT:
            self._debug("Heartbeat data")
        elif classified.kind == DataKind.ONLINE:
            if self._contains("online_data_map_lambda", data.get("rid")):
                self.cache.add(DataKind.ONLINE, data, timestamp=timestamp)
        elif classified.kind == DataKind.LATEST:
            if self._contains("latest_data_map_lambda", data.get("inter_id")):
                self.cache.add(DataKind.LATEST, data, timestamp=timestamp)
        elif classified.kind == DataKind.EXTEND:
            if self._contains("intersection_list", data.get("CrossId")):
                self.cache.add(DataKind.EXTEND, data, timestamp=timestamp)
        elif classified.kind == DataKind.OVERFLOW_WARNING:
            self._handle_overflow_warning(data)
        elif classified.kind == DataKind.RADAR:
            device_no = data.get("deviceNo")
            if self._contains("device_to_location", device_no):
                self.cache.add(DataKind.RADAR, data, timestamp=timestamp)
            self._debug(f"Processed radar data from device: {device_no}")
        elif classified.kind == DataKind.RADAR_EVENT:
            self._handle_radar_event(data)
        elif classified.kind == DataKind.BOYAN:
            device_id = data.get("deviceId")
            if self._contains("boyan_device_to_location", device_id):
                self.cache.add(DataKind.BOYAN, data, timestamp=timestamp)
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
        if (type_value in radar_event_list
            and self._contains("device_to_location", device_no)
            and self.radar_event_map is not None):
            self.radar_event_map[type_value][device_no] = data
        self._debug(f"Processed radar event from device: {device_no}")

    def _contains(self, attr_name: str, key: Any) -> bool:
        value = self._get_lambdas_attr(attr_name, None)
        return value is not None and key in value

    def _get_lambdas_attr(self, attr_name: str, default: Any) -> Any:
        return getattr(self.lambdas, attr_name, default) if self.lambdas is not None else default
