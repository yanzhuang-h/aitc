"""独立离线训练模块 - 周期识别、连续性与质量门禁算法 (Cycle Quality).

完全独立，零外部依赖，仅基于 Python 标准库。
"""

from __future__ import annotations

import math
from collections import Counter
from statistics import median

from .cleaner import clean_stage_inputs

WINDOW_SECONDS = 600
CYCLE_OBSERVATION_WINDOW_SECONDS = 900
LONG_CYCLE_THRESHOLD_SECONDS = 200
MIN_CONSECUTIVE_CYCLES = 3
MAX_ADJACENT_STAGE_CHANGE_SECONDS = 8


def group_continuous_stages(continuous_extend):
    """将逐秒阶段字典压缩为连续阶段列表。"""
    layers = []
    current_stage = None
    stage_start = None
    stage_end = None

    for current_time in sorted(continuous_extend):
        stage = continuous_extend[current_time]
        if current_stage is None:
            current_stage = stage
            stage_start = current_time
            stage_end = current_time
        elif stage == current_stage:
            stage_end = current_time
        else:
            layers.append({
                "stage": current_stage,
                "start": stage_start,
                "end": stage_end,
                "duration": stage_end - stage_start + 1,
            })
            current_stage = stage
            stage_start = current_time
            stage_end = current_time

    if current_stage is not None:
        layers.append({
            "stage": current_stage,
            "start": stage_start,
            "end": stage_end,
            "duration": stage_end - stage_start + 1,
        })
    return layers


def find_complete_cycles(layers, patterns, window_start, window_end):
    """在指定时间窗口内基于周期模板提取完整周期。"""
    if not layers or not patterns:
        return []

    cycles = []
    layer_count = len(layers)
    index = 0

    while index < layer_count:
        matched = False
        for pattern in patterns:
            pattern_length = len(pattern)
            if index + pattern_length > layer_count:
                continue

            candidate_layers = layers[index:index + pattern_length]
            stages = [layer["stage"] for layer in candidate_layers]

            if stages == pattern:
                cycle_start = candidate_layers[0]["start"]
                cycle_end = candidate_layers[-1]["end"]
                if (
                    int(window_start) <= cycle_start
                    and cycle_end <= int(window_end)
                ):
                    cycles.append({
                        "pattern": pattern,
                        "start": cycle_start,
                        "end": cycle_end,
                        "duration": cycle_end - cycle_start + 1,
                        "items": candidate_layers,
                    })
                    index += pattern_length
                    matched = True
                    break

        if not matched:
            index += 1

    return cycles


def find_complete_cycles_from_intervals(
    intervals,
    patterns,
    start_time,
    end_time,
):
    """从阶段区间中查找完全落在 [start_time, end_time] 内的完整周期。"""
    return find_complete_cycles(
        layers=intervals,
        patterns=patterns,
        window_start=start_time,
        window_end=end_time,
    )


def cycle_observation_expansion_decision(
    initial_cycles,
    long_cycle_threshold_seconds=LONG_CYCLE_THRESHOLD_SECONDS,
    statistic="median_of_initial_complete_cycles",
):
    """当周期过长时判断是否需要将观测窗口由 10min 扩展至 15min。"""
    if not initial_cycles:
        return {
            "should_expand": False,
            "reason": "no_complete_cycles",
            "cycle_count": 0,
            "cycle_durations": [],
            "median_duration_seconds": None,
            "threshold_seconds": long_cycle_threshold_seconds,
            "statistic": statistic,
        }

    durations = [int(cycle["duration"]) for cycle in initial_cycles]
    median_duration = float(median(durations))
    should_expand = median_duration > float(long_cycle_threshold_seconds)
    return {
        "should_expand": should_expand,
        "reason": (
            "median_cycle_exceeds_threshold"
            if should_expand
            else "median_cycle_within_threshold"
        ),
        "cycle_count": len(initial_cycles),
        "cycle_durations": durations,
        "median_duration_seconds": median_duration,
        "threshold_seconds": long_cycle_threshold_seconds,
        "statistic": statistic,
    }


def centered_observation_bounds(
    window_start,
    window_end,
    expanded_window_seconds=CYCLE_OBSERVATION_WINDOW_SECONDS,
):
    """以 10 分钟窗口为中心对称扩展至 15 分钟。"""
    window_start = int(window_start)
    window_end = int(window_end)
    target_seconds = int(expanded_window_seconds)
    flow_seconds = window_end - window_start + 1
    extra_seconds = max(0, target_seconds - flow_seconds)
    left_pad = extra_seconds // 2
    right_pad = extra_seconds - left_pad
    return window_start - left_pad, window_end + right_pad


def group_consecutive_same_pattern_cycles(cycles):
    """将连续且使用相同阶段模板的周期聚类成组。"""
    if not cycles:
        return []

    groups = []
    current_group = [cycles[0]]

    for cycle in cycles[1:]:
        previous_cycle = current_group[-1]
        same_pattern = cycle["pattern"] == previous_cycle["pattern"]
        adjacent = cycle["start"] == previous_cycle["end"] + 1
        if same_pattern and adjacent:
            current_group.append(cycle)
        else:
            groups.append(current_group)
            current_group = [cycle]

    if current_group:
        groups.append(current_group)
    return groups


def split_cycle_group_on_stage_change(
    cycle_group,
    max_adjacent_stage_change_seconds=MAX_ADJACENT_STAGE_CHANGE_SECONDS,
):
    """当相邻周期的同一阶段放行时长跳变超过阈值时断开分组。"""
    if not cycle_group:
        return []

    split_groups = []
    current_subgroup = [cycle_group[0]]

    for cycle in cycle_group[1:]:
        previous_cycle = current_subgroup[-1]
        has_large_jump = False
        for prev_item, curr_item in zip(previous_cycle["items"], cycle["items"]):
            if (
                abs(int(curr_item["duration"]) - int(prev_item["duration"]))
                > max_adjacent_stage_change_seconds
            ):
                has_large_jump = True
                break

        if has_large_jump:
            split_groups.append(current_subgroup)
            current_subgroup = [cycle]
        else:
            current_subgroup.append(cycle)

    if current_subgroup:
        split_groups.append(current_subgroup)
    return split_groups
