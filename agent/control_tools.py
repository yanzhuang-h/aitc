"""宿主绑定路口的认知工具；读取事实和候选，不重跑算法或写传感器状态。"""

import copy
import math
from collections import Counter
from dataclasses import fields
from itertools import islice
from typing import Any

from pydantic import TypeAdapter

from app.core.control.schemas import SignalPlan
from app.core.models.contract_types import NonEmptyString
from infra.data.datahub import SOURCE_KINDS, TrafficDataHub
from infra.data.traffic_schemas import ExpertTrafficState, TrafficDataView, TrafficSnapshot

from .actions import ACTION_ADAPTER, ToolAction, ToolObservation
from .experts._state import ExpertContractError


_ID_ADAPTER = TypeAdapter(NonEmptyString)
_SNAPSHOT_ADAPTER = TypeAdapter(TrafficSnapshot)
_VECTOR_FIELDS = ("traffic_vector", "traffic_vector_duration2", "queue_vector")
_MAP_FIELDS = ("flow_map", "queue_map", "stage_map", "extend_map", "radar_map", "boyan_map",
               "overflow_map", "predicted_flow", "predicted_queue", "previous_coordinate")
_GLOBAL_FIELDS = ("predicted_flow", "predicted_queue", "previous_coordinate")


def _sample(value: Any, depth: int = 0) -> Any:
    """映射最多三个条目、向量最多八项、两层嵌套，显式标记省略。"""
    if isinstance(value, str):
        return value[:200] + ("[omitted]" if len(value) > 200 else "")
    if type(value) is float:
        return value if math.isfinite(value) else {"omitted": "non_finite_number"}
    if value is None or type(value) in (bool, int):
        return value
    if not isinstance(value, (dict, list, tuple)):
        raise ExpertContractError("traffic state contains an unsupported summary value")
    if depth >= 2:
        return {"omitted": True, "entries": len(value)}
    if isinstance(value, dict):
        return {
            "sample": {str(key)[:80]: _sample(item, depth + 1)
                       for key, item in islice(value.items(), 3)},
            "entries": len(value), "truncated": len(value) > 3,
        }
    if isinstance(value, (list, tuple)):
        return {
            "sample": [_sample(item, depth + 1) for item in value[:8]],
            "entries": len(value), "truncated": len(value) > 8,
        }


def snapshot_summary(snapshot: TrafficSnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    values = {field.name: getattr(snapshot, field.name) for field in fields(snapshot)}
    omitted_not_scoped = []
    for name in _GLOBAL_FIELDS:
        mapping = values[name]
        if snapshot.cross_id in mapping:
            values[name] = {snapshot.cross_id: mapping[snapshot.cross_id]}
        else:
            values[name] = {}
            if mapping:
                omitted_not_scoped.append(name)
    summary = {
        "intersection_id": snapshot.cross_id,
        "current_time": snapshot.current_time,
        "available_fields": [name for name, value in values.items()
                             if name not in ("cross_id", "current_time") and value],
        "scoped_fields": list(_GLOBAL_FIELDS),
        "omitted_not_scoped": omitted_not_scoped,
    }
    for name in (*_VECTOR_FIELDS, *_MAP_FIELDS):
        value = values[name]
        if value:
            summary[name] = _sample(value)
    return summary


def expert_summary(state: ExpertTrafficState | None) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "source": state.source,
        "confidence": state.confidence,
        "missing_fields": [_sample(field) for field in state.missing_fields[:20]],
        "missing_fields_truncated": len(state.missing_fields) > 20,
        "observation": snapshot_summary(state.observation),
    }


class ControlAgentTools:
    def __init__(self, datahub: TrafficDataHub, video_expert, radar_expert) -> None:
        self.datahub = datahub
        self.video_expert = video_expert
        self.radar_expert = radar_expert

    @staticmethod
    def _expert(source, intersection_id, primary, fallback, extractor) -> ExpertTrafficState:
        existing = next((state for state in (primary, fallback)
                         if state is not None and state.source == source), None)
        state = ExpertTrafficState.model_validate(
            existing if existing is not None else extractor.extract(intersection_id),
        ).model_copy(deep=True)
        if state.source != source or state.observation.cross_id != intersection_id:
            raise ExpertContractError("expert result does not match the requested intersection and source")
        return state

    def execute(
        self, action: ToolAction, *, intersection_id: str,
        snapshot: TrafficSnapshot | None = None,
        primary: ExpertTrafficState | None = None,
        fallback: ExpertTrafficState | None = None,
        candidate: SignalPlan | None = None,
    ) -> ToolObservation:
        action = ACTION_ADAPTER.validate_python(action, strict=True).model_copy(deep=True)
        intersection_id = _ID_ADAPTER.validate_python(intersection_id, strict=True)
        if snapshot is not None:
            snapshot = copy.deepcopy(_SNAPSHOT_ADAPTER.validate_python(snapshot, strict=True))
            if snapshot.cross_id != intersection_id:
                raise ExpertContractError("snapshot belongs to another intersection")
        if candidate is not None:
            candidate = SignalPlan.model_validate(candidate).model_copy(deep=True)
            if candidate.intersection_id != intersection_id:
                raise ExpertContractError("candidate belongs to another intersection")
        for supplied, source in ((primary, "video"), (fallback, "radar")):
            if supplied is not None:
                checked = ExpertTrafficState.model_validate(supplied)
                if checked.source != source or checked.observation.cross_id != intersection_id:
                    raise ExpertContractError("supplied expert does not match the host intersection and source")

        tool = action.tool
        status = "ok"
        expert_state = None
        if tool == "query_traffic_state":
            source = action.arguments.source
            view = TrafficDataView.model_validate(self.datahub.query(
                intersection_id, source=source, include_snapshot=False,
            ))
            if (view.intersection_id != intersection_id or view.source != source
                    or any(event.intersection_id != intersection_id for event in view.events)
                    or (source is not None and any(event.kind not in SOURCE_KINDS[source]
                                                  for event in view.events))):
                raise ExpertContractError("DataHub view does not match the requested intersection and source")
            data = {
                "source": source,
                "event_count": len(view.events),
                "event_counts_by_kind": dict(Counter(event.kind.value for event in view.events)),
                "missing_fields": [_sample(field) for field in view.missing_fields[:20]],
                "missing_fields_truncated": len(view.missing_fields) > 20,
                "quality_issues": [_sample(issue) for issue in view.quality_issues[:20]],
                "quality_issues_truncated": len(view.quality_issues) > 20,
                "event_window_truncated": view.truncated,
                "snapshot_current_round": snapshot is not None,
                "snapshot": snapshot_summary(snapshot),
            }
            if snapshot is None:
                data["missing_fields"] = list(dict.fromkeys([*data["missing_fields"], "snapshot_current_round"]))
            if source in ("video", "radar"):
                extractor = self.video_expert if source == "video" else self.radar_expert
                expert_state = self._expert(source, intersection_id, primary, fallback, extractor)
                data["expert"] = expert_summary(expert_state)
            if not view.events and (source is not None or snapshot is None):
                status = "unavailable"
        elif tool == "query_history":
            history = self.datahub.history(intersection_id, limit=action.arguments.limit)
            if len(history) > action.arguments.limit:
                raise ExpertContractError("history exceeds the requested limit")
            snapshots = [copy.deepcopy(_SNAPSHOT_ADAPTER.validate_python(item, strict=True))
                         for item in history]
            if any(item.cross_id != intersection_id for item in snapshots):
                raise ExpertContractError("history contains another intersection")
            data = {
                "origin": "captured_history",
                "current_round_time": snapshot.current_time if snapshot is not None else None,
                "snapshots": [
                    {"history_position": index, "is_current_snapshot": item == snapshot,
                     **snapshot_summary(item)}
                    for index, item in enumerate(snapshots)
                ],
            }
            if not snapshots:
                status = "unavailable"
        elif tool in ("query_video_state", "query_radar_state"):
            source = "video" if tool == "query_video_state" else "radar"
            extractor = self.video_expert if source == "video" else self.radar_expert
            expert_state = self._expert(source, intersection_id, primary, fallback, extractor)
            data = expert_summary(expert_state)
            if expert_state.confidence == 0:
                status = "unavailable"
        elif tool == "run_control_policy":
            if candidate is None:
                status = "unavailable"
                data = {"reason": "candidate_not_available", "next_step": "run_control_policy"}
            else:
                data = {"candidate": candidate.model_dump(mode="json"), "algorithm_already_ran": True}
        elif tool == "review_signal_plan":
            if candidate is None:
                status = "unavailable"
                data = {"reason": "candidate_not_available"}
            else:
                data = {"review": action.arguments.model_dump(exclude_none=True), "advisory_only": True}
        else:  # discriminator 校验保证此处只剩 report_anomaly。
            data = {"reported_by": "model", "observation_verified": False,
                    "anomaly": action.arguments.model_dump()}
        return ToolObservation(
            tool=tool, intersection_id=intersection_id, status=status,
            data=copy.deepcopy(data), expert_state=expert_state,
        )
