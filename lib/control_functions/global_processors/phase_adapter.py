"""将方向累计绿灯需求转换为平台方案顺序的相位时间。

沿用训练侧的相位映射：单放相位同时服务直行和专用左转方向。
重复相位共同承担累计需求，不能简单重排方向向量或逐相位复制总时长。
"""

import math

from lib.data_ANS.cycle_quality import PHASE_DIRECTION_MAP as TRAINING_PHASE_DIRECTION_MAP

# 同义相位沿用训练侧方向语义；分段对放由重复相位共同分担累计需求。
PHASE_DIRECTION_MAP = {**TRAINING_PHASE_DIRECTION_MAP,
    "DU": ("U", "D"), "RL": ("L", "R"),
    "UD1": ("U", "D"), "UD2": ("U", "D"),
    "LR1": ("L", "R"), "LR2": ("L", "R"), "P": (),
}


def phase_bounds(state_config):
    phases = list(state_config["phase"][:8])
    active = [index for index, name in enumerate(phases) if name]
    if not active or active != list(range(len(active))):
        raise ValueError("platform phases must be nonempty and contiguous")
    phases = phases[:len(active)]
    minimums, maximums = [], []
    for index, phase in enumerate(phases):
        if phase not in PHASE_DIRECTION_MAP:
            raise ValueError(f"unsupported platform phase: {phase}")
        lows, highs = [], []
        for key in ("min_pass_time", "platform_min_pass_time"):
            values = state_config.get(key) or []
            lows.append(float(values[index]) if index < len(values) else 0)
        for key in ("max_pass_time", "platform_max_pass_time"):
            values = state_config.get(key) or []
            if index < len(values):
                value = float(values[index])
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"invalid phase maximum at {index}")
                if value > 0:
                    highs.append(value)
        if not all(math.isfinite(value) and value >= 0 for value in lows):
            raise ValueError(f"invalid phase minimum at {index}")
        # 下发协议在首个零值处结束，启用相位必须保持正时长。
        low = max(1, math.ceil(max(lows)))
        if not highs:
            raise ValueError(f"missing phase maximum at {index}")
        high = math.floor(min(highs))
        if low > high:
            raise ValueError(f"conflicting phase bounds at {index}: {low}>{high}")
        minimums.append(low)
        maximums.append(high)
    return phases, minimums, maximums


def complete_phase_cycle(times, minimums, maximums, minimum_cycle=60):
    """沿用最小周期规则，但逐相位受有效上下界约束；容量不足时明确记录缺口。"""
    times = [max(low, min(high, int(value)))
             for value, low, high in zip(times, minimums, maximums)]
    added = 0
    while sum(times) < minimum_cycle:
        eligible = [i for i, value in enumerate(times) if value < maximums[i]]
        if not eligible:
            break
        index = min(eligible, key=lambda i: (times[i] - minimums[i], i))
        times[index] += 1
        added += 1
    return times, {"cycle_extension_seconds": added,
                   "unmet_minimum_cycle_seconds": max(0, minimum_cycle-sum(times))}


def allocate_phase_times(demand, state_config):
    """在平台和信号机上下界内分配方向累计时间。

    从各相位最小绿开始，优先给能够同时覆盖最多未满足方向的相位加时，
    然后比较剩余缺口。同类重复相位按已增加的时间均衡分担需求。
    ponytail: 当前最多八个相位、单相位配置上限为数百秒，逐秒有界分配足够；
    若将来扩大规模，再替换为批量求解。这是确定性分配，不假设存在唯一反解。
    """
    phases, minimums, maximums = phase_bounds(state_config)
    movements = [PHASE_DIRECTION_MAP[name] for name in phases]
    targets = {}
    for direction, value in demand.items():
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"invalid movement demand: {direction}")
        targets[direction] = math.ceil(number)
    times = list(minimums)
    served = {direction: sum(times[i] for i, dirs in enumerate(movements)
                             if direction in dirs) for direction in targets}
    while True:
        remaining = {direction: max(0, value - served[direction])
                     for direction, value in targets.items()}
        candidates = [i for i, dirs in enumerate(movements)
                      if times[i] < maximums[i]
                      and any(remaining.get(d, 0) for d in dirs)]
        if not candidates:
            break
        def priority(index):
            dirs = movements[index]
            return (sum(remaining.get(d, 0) > 0 for d in dirs),
                    sum(remaining.get(d, 0) for d in dirs),
                    -(times[index] - minimums[index]), -index)
        index = max(candidates, key=priority)
        times[index] += 1
        for direction in movements[index]:
            if direction in served:
                served[direction] += 1
    times, cycle_audit = complete_phase_cycle(times, minimums, maximums)
    served = {direction: sum(times[i] for i, dirs in enumerate(movements)
                             if direction in dirs) for direction in targets}
    return times, {
        **cycle_audit,
        "phase_names": phases,
        "minimums": minimums,
        "maximums": maximums,
        "served_movement_times": served,
        "unmet_movement_times": {d: targets[d] - served[d] for d in targets
                                 if targets[d] > served[d]},
        "unmapped_movements": [d for d in targets if targets[d] > 0
                               and not any(d in dirs for dirs in movements)],
    }
