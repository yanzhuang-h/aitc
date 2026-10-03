"""保留原雷达与博研观测 map，不推导尚无业务定义的视频特征。"""

from infra.data import cache_processor
from infra.data.classifier import DataKind
from infra.data.datahub import TrafficDataHub
from infra.data.traffic_schemas import ExpertTrafficState

from ._state import empty_observation, expert_state, source_view


class RadarExpert:
    def __init__(self, datahub: TrafficDataHub) -> None:
        if datahub.lambdas is None:
            raise ValueError("RadarExpert requires DataHub device mappings")
        self.datahub = datahub

    def extract(self, intersection_id: str) -> ExpertTrafficState:
        observation = empty_observation(intersection_id)
        view = source_view(self.datahub, observation, "radar")
        radar = [(event.received_at, event.payload) for event in view.events if event.kind == DataKind.RADAR]
        boyan = [(event.received_at, event.payload) for event in view.events if event.kind == DataKind.BOYAN]
        if radar:
            observation.radar_map = cache_processor.process_radar_data(
                radar, self.datahub.lambdas,
            ).get(intersection_id, {})
        if boyan:
            observation.boyan_map = cache_processor.process_boyan_data(
                boyan, self.datahub.lambdas,
            ).get(intersection_id, {})
        # 原溢出处理跨来源合并并修改共享模板，专家不提前执行它。
        optional = ("overflow_map",) if any(event.kind == DataKind.RADAR_EVENT for event in view.events) else ()
        return expert_state(view, observation, required=("radar_map", "boyan_map"),
                            alternatives=True, optional=optional)
