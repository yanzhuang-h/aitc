"""旧接入数据和算法上下文到 V2 契约的适配，不替换生产接收器。"""

import copy
from dataclasses import asdict
from typing import Any, Mapping

from lib.control_functions.types import IntersectionControlRequest

from .classifier import DataSource, classify_data
from .contracts import validate_contract
from .traffic_schemas import RawTrafficEvent, TrafficSnapshot


def raw_event_from_legacy(
    payload: Mapping[str, Any],
    *,
    source: DataSource,
    received_at: int | float,
    intersection_id: str | None = None,
) -> RawTrafficEvent:
    classified = classify_data(payload, source)
    return RawTrafficEvent(
        kind=classified.kind, source=source, received_at=received_at,
        intersection_id=intersection_id, payload=copy.deepcopy(classified.item),
        quality_issues=validate_contract(classified.kind, classified.item, source),
    )


def raw_event_to_legacy(event: RawTrafficEvent) -> dict[str, Any]:
    return copy.deepcopy(event.payload)


def snapshot_from_legacy(request: IntersectionControlRequest) -> TrafficSnapshot:
    return TrafficSnapshot(**asdict(request))


def snapshot_to_legacy(snapshot: TrafficSnapshot) -> IntersectionControlRequest:
    return IntersectionControlRequest(**asdict(snapshot))
