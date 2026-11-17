"""缺经验时复用稳定反馈周期，不估造容量，也不写经验表。"""

from statistics import median

from lib.control_functions.global_processors.phase_adapter import allocate_phase_budget, allocate_phase_times, complete_phase_cycle, phase_bounds
from lib.data_ANS.lane_policy import configured_movement_lane_policy
from lib.data_ANS.phase_definitions import PHASE_DIRECTION_MAP


def observed_cycle_fallback(cycles, cross_config, road_programs, flow, decisions, min_green_time=1, max_green_time=150):
    """只替换与可靠经验相互独立的缺经验阶段组，保留缺流量阶段的反馈预算。"""
    names = [str(cross_config["phase"][stage]).upper() for stage in cycles[0]["pattern"]]
    movements = [set(PHASE_DIRECTION_MAP.get(name, ())) for name in names]
    if any(not directions for directions in movements):
        return {}, {"status": "non_vehicle_phase_requires_program_plan"}
    signature = [sorted(directions) for directions in movements]
    matches = []
    for program, config in road_programs.items():
        configured = list(config.get("phase", [])[:8])
        while configured and not configured[-1]:
            configured.pop()
        if [sorted(PHASE_DIRECTION_MAP.get(name, ())) for name in configured] == signature:
            _phases, lows, highs = phase_bounds(config)
            matches.append((str(program), lows, highs))
    if not matches:
        return {}, {"status": "no_matching_program_bounds"}
    lows = [max(item[1][i] for item in matches) for i in range(len(names))]
    highs = [min(item[2][i] for item in matches) for i in range(len(names))]
    if any(low > high for low, high in zip(lows, highs)):
        return {}, {"status": "conflicting_matching_program_bounds"}

    lanes = {direction: sorted(configured_movement_lane_policy(cross_config, direction)["eligible"])
             for direction in decisions}
    controlled = [{direction for direction in directions if lanes.get(direction)}
                  for directions in movements]
    protected = {direction for direction, decision in decisions.items()
                 if decision.get("experience_profile", {}).get("positive_capacity_points", 0) > 0}
    # 单放与共放相位可能相互覆盖；同一连通部分有可靠经验时整体保留原解。
    while True:
        expanded = protected | set().union(*(dirs for dirs in movements if dirs & protected))
        if expanded == protected:
            break
        protected = expanded
    cold = [i for i, dirs in enumerate(movements) if not dirs & protected]
    if not cold:
        return {}, {"status": "usable_experience_preserved"}
    if not any(decision.get("requested_flow", 0) > 0 for decision in decisions.values()):
        return {}, {"status": "no_positive_controlled_flow"}

    reference = [max(lows[i], min(highs[i], int(median(
        cycle["items"][i]["duration"] for cycle in cycles
    )))) for i in range(len(names))]
    reference, cycle_audit = complete_phase_cycle(reference, lows, highs)
    weights, effective_lows, effective_highs, held = [], [], [], []
    for i, dirs in enumerate(controlled):
        # 零计数不能证明方向无车；保留该阶段的有效反馈，不把预算挪给其他阶段。
        adjustable = i in cold and bool(dirs) and all(decisions[direction]["requested_flow"] > 0 for direction in dirs)
        if adjustable:
            weight = max(
                flow[direction][lane]
                for direction in dirs for lane in lanes[direction]
            )
            weights.append(weight)
            effective_lows.append(lows[i])
            effective_highs.append(highs[i])
        else:
            weights.append(0)
            effective_lows.append(reference[i])
            effective_highs.append(reference[i])
            held.append(i)
    times, budget_audit = allocate_phase_budget(
        weights, {"phase": names, "min_pass_time": effective_lows, "max_pass_time": effective_highs},
        sum(reference),
    )
    targets = {direction: sum(times[i] for i, dirs in enumerate(movements) if direction in dirs)
               for direction in set().union(*movements)}
    updates = {direction: targets[direction] for direction in set().union(*(movements[i] for i in cold))}
    if any(not min_green_time <= green <= max_green_time for green in updates.values()):
        return {}, {"status": "reference_exceeds_direction_time_bounds"}
    projected, _projection = allocate_phase_times(
        targets, {"phase": names, "min_pass_time": lows, "max_pass_time": highs},
    )
    if sum(projected) != sum(times):
        return {}, {"status": "direction_projection_changes_cycle_budget"}
    return updates, {
        "status": "observed_cycle_flow_budget", "reference_cycle_count": len(cycles),
        "matching_programs": [item[0] for item in matches], "phase_names": names,
        "reference_phase_times": reference, "allocated_phase_times": times,
        "minimums": lows, "maximums": highs, "flow_weights": weights,
        "held_phase_indexes": held, "cold_phase_indexes": cold,
        "direction_targets": updates, **cycle_audit, **budget_audit,
    }
