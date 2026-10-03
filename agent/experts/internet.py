"""互联网状态接口；单点契约尚不能承载全局路段协调上下文。"""

from infra.data.datahub import TrafficDataHub
from infra.data.traffic_schemas import ExpertTrafficState

from ._state import empty_observation


class InternetExpert:
    def __init__(self, datahub: TrafficDataHub) -> None:
        self.datahub = datahub

    def extract(self, intersection_id: str) -> ExpertTrafficState:
        empty_observation(intersection_id)
        # TODO: 明确全局路段状态如何进入专家 observation，再接入原互联网处理。
        raise NotImplementedError("InternetExpert requires a defined global road-state observation")
