"""SignalPlan 与既有十元素方案、TCP 报文的无损适配。"""

from typing import Any

from runtime.result_formatter import format_result

from .schemas import SignalPlan


def signal_plan_from_legacy(intersection_id: str, plan: list[Any] | tuple[Any, ...]) -> SignalPlan:
    if not isinstance(plan, (list, tuple)) or len(plan) != 10:
        raise ValueError("legacy signal plan must contain exactly 10 elements")
    return SignalPlan(
        intersection_id=intersection_id,
        phase_times=tuple(plan[:8]),
        reserved=plan[8],
        program_id=plan[9],
    )


def signal_plan_to_legacy(plan: SignalPlan) -> list[Any]:
    return [*plan.phase_times, plan.reserved, plan.program_id]


def signal_plan_to_payload(
    plan: SignalPlan,
    traffic_vector: list[Any],
    model_info_list: list[Any],
    *,
    lambdas_module: Any,
) -> dict[str, Any]:
    # 复用协议实现，保留零值截断、道路映射和随机诊断信息的原有语义。
    return format_result(
        plan.intersection_id, signal_plan_to_legacy(plan),
        traffic_vector, model_info_list, lambdas_module=lambdas_module,
    )
