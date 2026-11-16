"""Pure-flow intersection state selection."""

import json
import logging

from lib.road_groups import TONGZHOU_49, road_group
from lib.control_functions.global_processors.phase_adapter import allocate_phase_times, phase_bounds, complete_phase_cycle

LOGGER = logging.getLogger("FlowControl")


def select_flow_control_state(cross_id, demand, road_config, hour):
    if str(cross_id) in TONGZHOU_49:
        # 平台方案号不对应旧的 0/1/2 方向状态语义。
        # 使用配置中的默认方案，仍允许 road_state 显式指定其他方案。
        if "1" in road_config:
            return "1"
        raise ValueError("Tongzhou 49 default platform program 1 is missing")
    differences = [demand["R"] - demand["L"], demand["L"] - demand["R"], demand["D"] - demand["U"], demand["U"] - demand["D"]]
    state, maximum = "0", 0
    for index, value in enumerate(differences):
        if str(index + 1) in road_config and value > maximum:
            state, maximum = str(index + 1), value
    if maximum > 15:
        return state
    if hour < 5 and "5" in road_config:
        state = "5"
    # 与 V2.65 保持一致：部分路口的高峰强制状态带尾逗号（tuple）。
    # tuple 在后续 road_config[state] 查表时会抛 KeyError，整体回退到
    # 时段表方案（Get_time_map），这正是 V2.65 的原始行为，不能去掉。
    overrides = {
        "1700079": (((7, 9), "21"), ((16, 19), "16")),
        "1300306": (((7, 8), "21"), ((17, 18), "21")),
        "1700293": (((6, 6), "23"), ((7, 9), "22"), ((16, 19), "21")),
        "2702736": (((16, 19), ("21",)),),
        "1300255": (((6, 8), ("21",)),),
        "1300364": (((7, 8), ("4",)), ((16, 18), ("4",))),
        "1700124": (((7, 8), ("21",)), ((16, 19), ("21",))),
        "1300039": (((7, 8), ("2",)),),
        "1300108": (((16, 19), ("1",)),),
        "1300120": (((8, 11), ("2",)),),
    }
    for window, value in overrides.get(str(cross_id), ()):
        if window[0] <= hour <= window[1]:
            state = value
    return state


def generate_flow_phase_plan(plan, demand, state_config):
    """Generate flow phases using the legacy dedicated half-phase rules."""
    phases = state_config["phase"]
    # 两套下限逐相位取大（详见 mixed_control 同款说明），只增不减地兜底。
    signal_minimums = state_config.get("min_pass_time") or []
    platform_minimums = state_config.get("platform_min_pass_time") or []
    mins = [
        max(
            signal_minimums[i] if i < len(signal_minimums) else 0,
            platform_minimums[i] if i < len(platform_minimums) else 0,
        )
        for i in range(8)
    ]
    maxs = state_config["max_pass_time"]
    marks = {name: -1 for name in ("L", "R", "U", "D", "LR", "UD")}
    for i, name in enumerate(phases[:8]):
        if name in marks: marks[name] = i
    l, r, u, d = (demand[k] for k in ("L", "R", "U", "D"))
    for i, name in enumerate(phases[:8]):
        if name == "UD": value = max(u, d) if marks["U"] == marks["D"] == -1 else min(u, d) - (10 if marks["U"] != -1 and marks["D"] != -1 else 0)
        elif name in ("UD1", "UD2"): value = max(u, d) // 2
        elif name == "LR": value = max(l, r) if marks["L"] == marks["R"] == -1 else min(l, r) - (10 if marks["L"] != -1 and marks["R"] != -1 else 0)
        elif name in ("LR1", "LR2"): value = max(l, r) // 2
        elif name == "LRL": value = max(demand["LTL"], demand["RTL"]) + max(l, r) * .05
        elif name == "UDL": value = max(demand["UTL"], demand["DTL"]) + max(u, d) * .05
        elif name == "L": value = max(max(l-r, 0)+10, 15) if marks["R"] != -1 and marks["LR"] != -1 else (max(l-r, 15) if marks["LR"] != -1 else l)
        elif name == "R": value = max(max(r-l, 0)+10, 15) if marks["L"] != -1 and marks["LR"] != -1 else (max(r-l, 15) if marks["LR"] != -1 else r)
        elif name in ("U", "D"):
            own, other, other_mark = (u, d, marks["D"]) if name == "U" else (d, u, marks["U"])
            value = max(max(u-d, 0)+10, 15, max(d-u, 0)+10) if other_mark != -1 and marks["UD"] != -1 else (max(own-other, 15) if marks["UD"] != -1 else own)
        elif name == "P":
            plan[i] = sum(plan[:10]) * .25 + mins[i]
            continue
        else: continue
        plan[i] = max(min(value, maxs[i]), mins[i])
    return plan


def _process_legacy_flow_intersection(cross_id, current_plan, road_config, hour,
                              forced_state_selector, schedule_loader):
    """Run one complete pure-flow intersection branch."""
    report = {"success": False, "cross_id": str(cross_id), "state": None,
              "fallback": None, "error": None}
    try:
        if current_plan == [0] * 10:
            plan = schedule_loader(int(cross_id))[str(hour)]
            report.update({"success": True, "fallback": "time_schedule"})
            return plan, report
        demand = {"L": max(current_plan[2], 0), "R": max(current_plan[3], 0),
                  "U": max(current_plan[0], 0), "D": max(current_plan[1], 0),
                  "UTL": current_plan[4], "DTL": current_plan[5],
                  "LTL": current_plan[6], "RTL": current_plan[7]}
        for index in range(8):
            current_plan[index] = 0
        state = select_flow_control_state(cross_id, demand, road_config, hour)
        state = forced_state_selector(str(cross_id), state)
        generate_flow_phase_plan(current_plan, demand, road_config[state])
        current_plan[9] = int(state)
        report.update({"success": True, "state": state})
        return current_plan, report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        # 与 V2.65 的内层 try/except 语义一致：状态计算或相位生成
        # 异常时保持当前 plan（已清零，交由后续最小周期等公共处理），
        # 不在这里回退时段表。
        return current_plan, report


def _process_tongzhou_intersection(cross_id, current_plan, road_config, hour,
                                  forced_state_selector, schedule_loader):
    report = {"success": False, "cross_id": str(cross_id), "state": None,
              "fallback": None, "error": None}
    try:
        default_state = select_flow_control_state(cross_id, {}, road_config, hour)
        state = str(forced_state_selector(str(cross_id), default_state))
        report["state"] = state
        if state not in road_config:
            raise ValueError(f"selected platform program {state} is missing")
        if len(current_plan) != 10:
            raise ValueError("direction vector must contain ten slots")
        directions = ("U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL")
        demand = dict(zip(directions, current_plan[:8]))
        if not any(current_plan[:8]):
            # 时刻表按默认方案排列，不能将其位置时间套给相位顺序不同的强制方案。
            if state == default_state:
                vector = list(schedule_loader(int(cross_id))[str(hour)])
                if len(vector) != 10:
                    raise ValueError("timetable vector must contain ten slots")
                phases, lows, highs = phase_bounds(road_config[state])
                times = [max(low, min(high, int(vector[i])))
                         for i, (low, high) in enumerate(zip(lows, highs))]
                times, cycle_audit = complete_phase_cycle(times, lows, highs)
                audit = {"phase_names": phases, "minimums": lows, "maximums": highs,
                         **cycle_audit}
                report["fallback"] = "time_schedule"
            else:
                times, audit = allocate_phase_times(demand, road_config[state])
                report["fallback"] = "forced_program_minimums"
        else:
            times, audit = allocate_phase_times(demand, road_config[state])
        plan = times + [0] * (10 - len(times))
        plan[9] = int(state)
        report.update(audit)
        report["quality_issues"] = []
        if audit.get("unmapped_movements"):
            report["quality_issues"].append("program_does_not_cover_all_movements")
        if audit.get("unmet_movement_times"):
            report["quality_issues"].append("movement_targets_not_fully_met")
        report["success"] = True
        return plan, report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        # 转换失败时只允许回退至经过边界校验的默认方案；不把方向向量当相位下发。
        try:
            default = "1"
            phases, lows, highs = phase_bounds(road_config[default])
            try:
                vector = list(schedule_loader(int(cross_id))[str(hour)])
                if len(vector) != 10:
                    raise ValueError("invalid fallback timetable")
                times = vector[:len(phases)]
                fallback = "validated_default_timetable"
            except (KeyError, TypeError, ValueError, OSError):
                times = lows
                fallback = "validated_default_minimums"
            times, cycle_audit = complete_phase_cycle(times, lows, highs)
            plan = times + [0] * (10-len(times))
            plan[9] = 1
            report.update({"success": True, "state": default, "fallback": fallback,
                           "phase_names": phases, "minimums": lows, "maximums": highs,
                           **cycle_audit})
            return plan, report
        except Exception as fallback_error:
            report["fallback_error"] = f"{type(fallback_error).__name__}: {fallback_error}"
            return [0] * 10, report


def process_flow_intersection(cross_id, current_plan, road_config, hour,
                              forced_state_selector, schedule_loader):
    original = list(current_plan)
    processor = (_process_tongzhou_intersection if str(cross_id) in TONGZHOU_49
                 else _process_legacy_flow_intersection)
    plan, report = processor(cross_id, current_plan, road_config, hour,
                             forced_state_selector, schedule_loader)
    report["road_group"] = road_group(cross_id)
    report["input_direction_vector"] = original
    report["adapted_phase_vector"] = list(plan)
    report["is_final"] = False
    if report["road_group"] is not None:
        LOGGER.info("flow_control %s", json.dumps(report, separators=(",", ":")))
    return plan, report
