"""专家共用的边界校验和覆盖度描述，不调模型或控制器。"""

import time

from infra.data.datahub import SOURCE_KINDS, TrafficDataHub
from infra.data.traffic_schemas import (
    ExpertTrafficState, TrafficDataView, TrafficSnapshot, TrafficSource,
)


class ExpertContractError(ValueError):
    """明确的来源/路口边界故障，编排层可报告并转读其他来源。"""


def empty_observation(intersection_id: str) -> TrafficSnapshot:
    return TrafficSnapshot(cross_id=intersection_id, current_time=time.time())


def source_view(hub: TrafficDataHub, observation: TrafficSnapshot, source: TrafficSource) -> TrafficDataView:
    view = TrafficDataView.model_validate(hub.query(
        observation.cross_id, source=source, include_snapshot=False,
    ))
    if view.source != source or view.intersection_id != observation.cross_id:
        raise ExpertContractError("DataHub view does not match the requested intersection and source")
    if any(event.intersection_id != observation.cross_id for event in view.events):
        raise ExpertContractError("DataHub event belongs to another intersection")
    if any(event.kind not in SOURCE_KINDS[source] for event in view.events):
        raise ExpertContractError("DataHub event does not belong to the requested source")
    return view


def expert_state(
    view: TrafficDataView, observation: TrafficSnapshot, *,
    required: tuple[str, ...], optional: tuple[str, ...] = (),
    alternatives: bool = False, degraded: bool = False,
) -> ExpertTrafficState:
    available = [bool(getattr(observation, field)) for field in required]
    confidence = float(any(available)) if alternatives else sum(available) / len(required)
    missing = [field for field in (*required, *optional) if not getattr(observation, field)]
    # 控制快照缺失与当前来源数据无关；原报文缺失仍保留供路由判断。
    missing.extend(field for field in view.missing_fields if "." in field or field == "event_capture")
    if view.truncated:
        missing.append("event_window")
    if (degraded or view.truncated or "event_capture" in view.missing_fields
            or any(event.quality_issues for event in view.events)):
        confidence = min(confidence, 0.5)
    return ExpertTrafficState(
        source=view.source, observation=observation,
        missing_fields=list(dict.fromkeys(missing)), confidence=confidence,
    )
