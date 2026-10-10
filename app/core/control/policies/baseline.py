"""封装当前规则、经验、时刻表与全局协调，不改算法内部行为。"""

from typing import Any, Callable

from pydantic import TypeAdapter

from app.core.control.adapters import signal_plan_from_legacy
from app.core.control.schemas import SignalPlan
from infra.data.traffic_adapters import snapshot_to_legacy
from infra.data.traffic_schemas import TrafficSnapshot
from lib.control_functions.types import IntersectionControlRequest


LegacySelection = tuple[Any, Any, Any, Any]
_SNAPSHOT_ADAPTER = TypeAdapter(TrafficSnapshot)


class BaselineController:
    """单点候选与全局协调共用旧算法，诊断随调用返回而不存共享状态。"""

    def __init__(
        self,
        *,
        selector: Callable[[IntersectionControlRequest], LegacySelection] | None = None,
        coordinator: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        if selector is None:
            from lib.control_functions.dqn_control import call_dqn_select

            selector = call_dqn_select
        if coordinator is None:
            from lib.Global_intersection_coordinate import coordinate

            coordinator = coordinate
        self._selector = selector
        self._coordinator = coordinator

    def predict(self, state: TrafficSnapshot) -> SignalPlan:
        """独立计算单路口候选；最终输出仍需全局协调和确定性校验。"""
        snapshot = _SNAPSHOT_ADAPTER.validate_python(state)
        plan, _, _, _ = self.select_legacy(snapshot_to_legacy(snapshot))
        return signal_plan_from_legacy(snapshot.intersection_id, plan)

    def select_legacy(self, request: IntersectionControlRequest) -> LegacySelection:
        """生产兼容入口：保留原始方案、诊断、对象引用及异常传播。"""
        return self._selector(request)

    def fallback_legacy(self, intersection_id: str, current_time: float) -> Any:
        """复用原工作日/周末时刻表；由 Safety Gate 校验，不能直接发送。"""
        import copy
        import time
        from lib.AITC_tool import Get_time_map

        schedule = Get_time_map(intersection_id)
        return copy.deepcopy(schedule.get(str(time.localtime(current_time).tm_hour))) if schedule else None

    def coordinate_legacy(
        self,
        action: dict[str, Any],
        coordinate_map: dict[str, Any],
        online_map: dict[str, Any],
        overflow_map: dict[str, Any],
    ) -> dict[str, Any]:
        # 生产原入口只传四参数，额外传 extend 会改变现有绿波输入。
        return self._coordinator(action, coordinate_map, online_map, overflow_map)
