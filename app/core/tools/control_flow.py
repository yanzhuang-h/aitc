"""单路口放行控制的分步流程规则。

本模块只包含"函数判断"部分：每个步骤接收累积上下文，输出结构化结果，
不依赖大模型。大模型只负责为每一步生成可展示的思考说明，见
``agent/control_agent.py``。

规则刻意保持简单（先上架、后续再细化），方向级数据默认使用模拟样例；
如果数据底座能查到该路口的真实运行数据，会以摘要形式附加到输入信息。
"""

from __future__ import annotations

from typing import Any

# 默认模拟数据：前 10 分钟方向级车流状态
DEFAULT_TRAFFIC_STATE: dict[str, dict[str, Any]] = {
    "东西直行": {"avg_flow": 780, "avg_density": 56, "avg_speed": 15, "avg_queue_length": 135},
    "东西左转": {"avg_flow": 260, "avg_density": 32, "avg_speed": 22, "avg_queue_length": 65},
    "南北直行": {"avg_flow": 430, "avg_density": 28, "avg_speed": 29, "avg_queue_length": 48},
    "南北左转": {"avg_flow": 180, "avg_density": 20, "avg_speed": 31, "avg_queue_length": 30},
}

# 通车能力评估表（密度区间 -> 建议权重）
DEFAULT_CAPACITY_TABLE: dict[str, dict[str, str]] = {
    "low_pressure": {"density_range": "0-25", "suggested_weight": "0.10-0.20"},
    "medium_pressure": {"density_range": "25-40", "suggested_weight": "0.20-0.35"},
    "high_pressure": {"density_range": "40-55", "suggested_weight": "0.35-0.50"},
    "severe_pressure": {"density_range": "55+", "suggested_weight": "0.50+"},
}

# 信号控制约束
DEFAULT_SIGNAL_CONSTRAINTS: dict[str, Any] = {
    "cycle": 120,
    "yellow": 3,
    "all_red": 2,
    "min_green": 10,
    "max_green": 60,
    "pedestrian_min_green": {"东西直行": 25, "南北直行": 28},
}


def build_initial_context(
    cross_id: str,
    traffic_state: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """构造流程累积上下文。"""
    return {
        "cross_id": str(cross_id),
        "traffic_state": dict(traffic_state or DEFAULT_TRAFFIC_STATE),
        "capacity_table": DEFAULT_CAPACITY_TABLE,
        "constraints": DEFAULT_SIGNAL_CONSTRAINTS,
    }


def query_data_hub_summary(cross_id: str, query_service: Any | None) -> dict[str, Any] | None:
    """从数据底座查询该路口的真实运行数据摘要；无数据或异常返回 None。"""
    if query_service is None:
        return None
    try:
        flow = query_service.get_runtime_data("flow", limit=50) or []
        queue = query_service.get_runtime_data("queue", limit=50) or []
        flow_self = [r for r in flow if str(r.get("intersection_id", "")) == str(cross_id)]
        queue_self = [r for r in queue if str(r.get("intersection_id", "")) == str(cross_id)]
        if not flow_self and not queue_self:
            return None

        def _avg_count(records: list[dict[str, Any]]) -> float:
            values = [r.get("payload", {}).get("count") for r in records]
            values = [v for v in values if isinstance(v, (int, float))]
            return round(sum(values) / len(values), 1) if values else 0.0

        return {
            "flow_records": len(flow_self),
            "queue_records": len(queue_self),
            "avg_flow_count": _avg_count(flow_self),
            "avg_queue_count": _avg_count(queue_self),
        }
    except Exception:
        return None


def step_task_summary(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 1：任务与输入信息摘要。"""
    result = {
        "intersection_id": context["cross_id"],
        "time_window": "past_10_minutes",
        "traffic_state": context["traffic_state"],
        "capacity_evaluation_table": context["capacity_table"],
        "signal_constraints": context["constraints"],
    }
    if context.get("data_hub"):
        result["data_hub"] = context["data_hub"]
    context["input_summary"] = result
    return result


def step_anomaly_detect(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 2：车流异常检测（按密度找最大压力方向）。"""
    traffic = context["traffic_state"]
    worst = max(traffic, key=lambda d: traffic[d]["avg_density"])
    density = traffic[worst]["avg_density"]
    severity = "high" if density >= 55 else "medium" if density >= 40 else "low"
    abnormal = severity != "low"
    result = {
        "abnormal": abnormal,
        "abnormal_type": f"{worst}高压力接近严重拥堵" if abnormal else "整体压力正常",
        "severity": severity,
        "affected_movements": [worst] if abnormal else [],
    }
    context["anomaly"] = result
    return result


def step_anomaly_handle(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 3：异常处理策略（确定优先/次要/抑制方向）。"""
    traffic = context["traffic_state"]
    ranked = sorted(traffic, key=lambda d: traffic[d]["avg_density"], reverse=True)
    priority, secondary, suppressed = ranked[0], ranked[1], ranked[-1]
    result = {
        "priority_movements": [priority],
        "secondary_movements": [secondary],
        "suppressed_movements": [suppressed],
        "strategy": f"提高{priority}通行权重，保障其他方向最低服务",
    }
    context["handling"] = result
    return result


def step_single_point_weight(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 4：单点路口通行权重（按密度归一化）。"""
    traffic = context["traffic_state"]
    densities = {d: max(float(traffic[d]["avg_density"]), 1.0) for d in traffic}
    total = sum(densities.values()) or 1.0
    weights = {d: round(densities[d] / total, 3) for d in traffic}
    context["single_weights"] = weights
    return {"single_point_weight": weights}


def step_global_weight(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 5：全局路口通行权重（给优先方向小幅加成）。"""
    single = context["single_weights"]
    handling = context["handling"]
    priority = handling["priority_movements"][0]
    suppressed = handling["suppressed_movements"][0]
    weights = dict(single)
    bonus = 0.02
    weights[priority] = round(weights[priority] + bonus, 3)
    weights[suppressed] = round(weights[suppressed] - bonus, 3)
    context["global_weights"] = weights
    return {
        "global_context": {
            "main_corridor": "东西向",
            "downstream_spillback_risk": "low",
            "upstream_pressure": "medium_high",
        },
        "global_weight": weights,
    }


def step_fuse_weight(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 6：权重融合（0.6 单点 + 0.4 全局）。"""
    single = context["single_weights"]
    global_ = context["global_weights"]
    fused = {d: round(0.6 * single[d] + 0.4 * global_[d], 3) for d in single}
    context["fused_weights"] = fused
    return {"fused_weight": fused, "fusion": "0.6*single + 0.4*global"}


def _allocate_greens(weights: dict[str, float], available: int) -> dict[str, int]:
    """按权重分配整数绿灯，用最大余数法保证总和精确等于 available。"""
    raw = {m: weights[m] * available for m in weights}
    greens = {m: int(raw[m]) for m in weights}
    deficit = available - sum(greens.values())
    for m in sorted(greens, key=lambda x: raw[x] - int(raw[x]), reverse=True)[:deficit]:
        greens[m] += 1
    return greens


def step_to_signal_plan(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 7：权重转换为信号控制方案。"""
    fused = context["fused_weights"]
    constraints = context["constraints"]
    cycle = int(constraints["cycle"])
    yellow = int(constraints["yellow"])
    all_red = int(constraints["all_red"])
    movements = list(fused.keys())
    loss = len(movements) * (yellow + all_red)
    available = cycle - loss
    greens = _allocate_greens(fused, available)
    phases = []
    for index, movement in enumerate(movements, start=1):
        phases.append({
            "phase_id": f"P{index}",
            "movement": movement,
            "green": greens[movement],
            "yellow": yellow,
            "all_red": all_red,
        })
    result = {"cycle": cycle, "available_green": available, "phases": phases}
    context["raw_plan"] = result
    return result


def step_safety_check(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 8：安全检查（绿灯上下限与行人最小绿）。"""
    plan = context["raw_plan"]
    constraints = context["constraints"]
    min_green = int(constraints["min_green"])
    max_green = int(constraints["max_green"])
    ped_min = constraints.get("pedestrian_min_green", {})
    issues = []
    for phase in plan["phases"]:
        green = int(phase["green"])
        if green < min_green or green > max_green:
            issues.append({
                "type": "green_out_of_range",
                "phase_id": phase["phase_id"],
                "movement": phase["movement"],
                "current_green": green,
                "required_green": f"{min_green}-{max_green}",
            })
        required = ped_min.get(phase["movement"])
        if required and green < required:
            issues.append({
                "type": "pedestrian_green_insufficient",
                "phase_id": phase["phase_id"],
                "movement": phase["movement"],
                "current_green": green,
                "required_green": required,
            })
    result = {"safe": not issues, "issues": issues}
    context["safety"] = result
    return result


def step_repair(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 9：安全修正（优先从非优先方向回收绿灯补足行人最小绿）。"""
    plan = context["raw_plan"]
    safety = context["safety"]
    constraints = context["constraints"]
    min_green = int(constraints["min_green"])
    priority = context["handling"]["priority_movements"][0]
    phases = [dict(phase) for phase in plan["phases"]]

    for issue in safety["issues"]:
        if issue["type"] != "pedestrian_green_insufficient":
            continue
        phase = next(p for p in phases if p["phase_id"] == issue["phase_id"])
        deficit = int(issue["required_green"]) - int(phase["green"])
        if deficit <= 0:
            continue
        candidates = [
            p for p in phases
            if p["phase_id"] != issue["phase_id"]
            and p["movement"] != priority
            and int(p["green"]) - deficit >= min_green
        ]
        for candidate in candidates:
            take = min(deficit, int(candidate["green"]) - min_green)
            if take > 0:
                candidate["green"] = int(candidate["green"]) - take
                phase["green"] = int(phase["green"]) + take
                deficit -= take
            if deficit <= 0:
                break
        if deficit > 0:
            priority_phase = next(p for p in phases if p["movement"] == priority)
            take = min(deficit, int(priority_phase["green"]) - min_green)
            if take > 0:
                priority_phase["green"] = int(priority_phase["green"]) - take
                phase["green"] = int(phase["green"]) + take

    repaired = {"cycle": plan["cycle"], "phases": phases}
    context["repaired_plan"] = repaired
    return {"repaired_signal_plan": repaired}


def step_finalize(context: dict[str, Any]) -> dict[str, Any]:
    """步骤 10：最终方案组装与下发决策。"""
    plan = context["repaired_plan"]
    result = {
        "final_control_plan": {
            "intersection_id": context["cross_id"],
            "control_type": "single_release_weight_based",
            "cycle": plan["cycle"],
            "effective_for": "next_cycle",
            "phases": plan["phases"],
            "dispatch_decision": {
                "allow_dispatch": True,
                "reason": "方案已完成安全修正并通过复检",
            },
        }
    }
    context["final_plan"] = result["final_control_plan"]
    return result


# 分步流程定义：key / 展示标题 / 规则函数
CONTROL_STEPS: list[dict[str, Any]] = [
    {"key": "task_summary", "title": "任务与输入摘要", "fn": step_task_summary},
    {"key": "anomaly_detect", "title": "车流异常检测", "fn": step_anomaly_detect},
    {"key": "anomaly_handle", "title": "异常处理策略", "fn": step_anomaly_handle},
    {"key": "single_point_weight", "title": "单点权重生成", "fn": step_single_point_weight},
    {"key": "global_weight", "title": "全局权重生成", "fn": step_global_weight},
    {"key": "fuse_weight", "title": "权重融合", "fn": step_fuse_weight},
    {"key": "to_signal_plan", "title": "信号控制方案生成", "fn": step_to_signal_plan},
    {"key": "safety_check", "title": "安全检查", "fn": step_safety_check},
    {"key": "repair", "title": "安全修正", "fn": step_repair},
    {"key": "finalize", "title": "最终方案与总结", "fn": step_finalize},
]
