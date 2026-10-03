"""从当前视频事件构建状态，复用原聚合，保留真实字段和时间边界。"""

import math

from app.config import RuntimeSettings
from infra.data import cache_processor
from infra.data.classifier import DataKind
from infra.data.datahub import TrafficDataHub
from infra.data.traffic_schemas import ExpertTrafficState

from ._state import empty_observation, expert_state, source_view


def _counted_flow(flow_map: dict) -> int:
    return sum(sum(record["count"].values()) for record in flow_map.values())


def _nonnegative_number(value) -> bool:
    return (type(value) is int or (type(value) is float and math.isfinite(value))) and value >= 0


def _lane_valid(value, width: int) -> bool:
    if type(value) not in (int, str):
        return False
    try:
        lane = int(value)
    except ValueError:
        return False
    return 0 <= lane < width


def _observed_queue(queue_map: dict) -> bool:
    # 实际桶可含零排队；模板中的全零、无效数字都不能证明已观测。
    return bool(queue_map) and all(
        _nonnegative_number(value)
        for record in queue_map.values()
        for metric in ("queue", "all")
        for lanes in record[metric].values()
        for value in lanes
    )


class VideoExpert:
    """必要观测为 flow_map 和 queue_map；其余字段独立报告缺失。"""

    def __init__(
        self, datahub: TrafficDataHub, *,
        flow_duration_seconds: int = RuntimeSettings.flow_duration_seconds,
    ) -> None:
        if datahub.lambdas is None:
            raise ValueError("VideoExpert requires DataHub intersection mappings")
        if type(flow_duration_seconds) is not int or flow_duration_seconds <= 0:
            raise ValueError("flow_duration_seconds must be a positive integer")
        self.datahub = datahub
        self.flow_duration_seconds = flow_duration_seconds

    def extract(self, intersection_id: str) -> ExpertTrafficState:
        observation = empty_observation(intersection_id)
        view = source_view(self.datahub, observation, "video")
        lambdas = self.datahub.lambdas
        events = {kind: [event for event in view.events if event.kind == kind]
                  for kind in (DataKind.FLOW, DataKind.QUEUE, DataKind.STAGE, DataKind.EXTEND)}
        degraded = False
        if events[DataKind.FLOW]:
            width = max(len(lanes) for lanes in lambdas.flow_map_single_intersection_lambda["pass"].values())
            invalid_lanes = any(not _lane_valid(event.payload.get("ycsb_cdbh"), width)
                                for event in events[DataKind.FLOW])
            if invalid_lanes:
                view.missing_fields.append("flow.ycsb_cdbh")
            vectors, maps = cache_processor.process_flow_data(
                [event.payload for event in events[DataKind.FLOW]], lambdas,
            )
            flow_map = maps.get(intersection_id, {})
            counted = _counted_flow(flow_map)
            if counted and not invalid_lanes:
                observation.traffic_vector = vectors[intersection_id]
                observation.flow_map = flow_map
            degraded = invalid_lanes or counted != len(events[DataKind.FLOW])
            short_events = [event.payload for event in events[DataKind.FLOW]
                            if observation.current_time - event.received_at < self.flow_duration_seconds]
            if short_events:
                short_vectors, short_maps = cache_processor.process_flow_data(short_events, lambdas)
                if (_counted_flow(short_maps.get(intersection_id, {}))
                        and all(_lane_valid(data.get("ycsb_cdbh"), width) for data in short_events)):
                    observation.traffic_vector_duration2 = short_vectors[intersection_id]
        if events[DataKind.QUEUE]:
            invalid_lanes = any(
                not isinstance(event.payload.get("car_nums"), list)
                or any(not isinstance(record, dict) or not _lane_valid(record.get("ycsb_cdbh"), 7)
                       for record in event.payload["car_nums"])
                for event in events[DataKind.QUEUE]
            )
            if invalid_lanes:
                view.missing_fields.append("queue.car_nums.ycsb_cdbh")
            vectors, maps = cache_processor.process_queue_data(
                [event.payload for event in events[DataKind.QUEUE]], lambdas,
            )
            queue_map = maps.get(intersection_id, {})
            queue_vector = vectors.get(intersection_id, {})
            valid_vector = bool(queue_vector) and all(
                _nonnegative_number(value) for lanes in queue_vector.values() for value in lanes
            )
            if not invalid_lanes and valid_vector and _observed_queue(queue_map):
                observation.queue_vector = vectors[intersection_id]
                observation.queue_map = queue_map
            elif queue_map or invalid_lanes:
                degraded = True
        if events[DataKind.STAGE]:
            observation.stage_map = cache_processor.process_stage_data(
                [event.payload for event in events[DataKind.STAGE]], lambdas,
            ).get(intersection_id, {})
        if events[DataKind.EXTEND]:
            observation.extend_map = cache_processor.process_extend_data(
                [(event.received_at, event.payload) for event in events[DataKind.EXTEND]], lambdas,
            ).get(intersection_id, {})
        optional = ("stage_map", "extend_map", "traffic_vector_duration2")
        if any(event.kind == DataKind.OVERFLOW_WARNING for event in view.events):
            optional += ("overflow_map",)
        return expert_state(view, observation, required=("flow_map", "queue_map"),
                            optional=optional, degraded=degraded)
