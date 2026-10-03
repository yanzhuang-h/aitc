"""EV/V2X 状态接口；当前没有已接线的原始数据与映射定义。"""

from infra.data.datahub import TrafficDataHub
from infra.data.traffic_schemas import ExpertTrafficState

from ._state import empty_observation


class EVExpert:
    def __init__(self, datahub: TrafficDataHub) -> None:
        self.datahub = datahub

    def extract(self, intersection_id: str) -> ExpertTrafficState:
        empty_observation(intersection_id)
        # TODO: 确认 EV/V2X 接入字段和设备映射后实现，不伪造空的成功状态。
        raise NotImplementedError("EVExpert has no connected EV/V2X input contract")
