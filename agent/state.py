"""每次图调用独立持有上下文和结果，不在共享 Harness 保存诊断。"""

from dataclasses import dataclass
from typing import Callable, TypedDict

from app.core.control.policies.baseline import LegacySelection
from app.core.control.schemas import SignalPlan
from infra.data.traffic_schemas import ExpertTrafficState, TrafficSnapshot
from lib.control_functions.types import IntersectionControlRequest


@dataclass(frozen=True)
class ControlContext:
    request: IntersectionControlRequest
    selector: Callable[[IntersectionControlRequest], LegacySelection]
    strict: bool = False
    snapshot: TrafficSnapshot | None = None


class ControlState(TypedDict, total=False):
    intersection_id: str
    request: IntersectionControlRequest
    snapshot: TrafficSnapshot | None
    primary: ExpertTrafficState | None
    fallback: ExpertTrafficState | None
    used_fallback: bool
    selection: LegacySelection
    candidate: SignalPlan | None
    quality_issues: tuple[str, ...]
    route: tuple[str, ...]


@dataclass(frozen=True)
class ControlDecision:
    """候选及本轮路由证据；最终方案仍由批次协调和 phase_check 产生。"""

    selection: LegacySelection
    candidate: SignalPlan | None
    primary: ExpertTrafficState | None
    fallback: ExpertTrafficState | None
    used_fallback: bool
    quality_issues: tuple[str, ...]
    route: tuple[str, ...]
