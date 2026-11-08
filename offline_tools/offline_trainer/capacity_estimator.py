"""独立离线训练模块 - 核心通行能力特征提取 (Capacity Estimator / E_T).

根据历史流量和信控放行日志，基于周期识别提取不同绿灯秒数下的各车道极限通行能力。
完全独立，零外部依赖，仅基于 Python 标准库。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta

from .candidate_audit import ExperienceCandidateAudit
from .cleaner import DEFAULT_MAX_STAGE_GAP_SECONDS, clean_training_inputs
from .cycle_quality import (
    CYCLE_OBSERVATION_WINDOW_SECONDS,
    LONG_CYCLE_THRESHOLD_SECONDS,
    MAX_ADJACENT_STAGE_CHANGE_SECONDS,
    MIN_CONSECUTIVE_CYCLES,
    WINDOW_SECONDS,
    centered_observation_bounds,
    cycle_observation_expansion_decision,
    find_complete_cycles_from_intervals,
    group_consecutive_same_pattern_cycles,
    split_cycle_group_on_stage_change,
)
from .lane_policy import (
    BASE_DIRECTIONS,
    capacity_experience_direction,
    classify_lane_type,
    is_dedicated_left,
)

BASE_FLOW_DIRECTIONS = ("U", "D", "L", "R")
PHASE_DIRECTION_MAP = {
    "UD": ("U", "D"),
    "LR": ("L", "R"),
    "UDL": ("UTL", "DTL"),
    "LRL": ("LTL", "RTL"),
    "U": ("U", "UTL"),
    "D": ("D", "DTL"),
    "L": ("L", "LTL"),
    "R": ("R", "RTL"),
    "LTD": ("LTL", "D"),
}


def _time_seconds(value):
    value = int(value)
    if value > 10_000_000_000:
        value //= 1000
    if value <= 0:
        raise ValueError("timestamp must be positive")
    return value


def _load_json(path, default=None):
    """加载 JSON 文件；文件不存在时返回 default。"""
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _write_json_atomic(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False
        ) as file:
            temp_path = file.name
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def sort_by_time(data):
    """按绿灯秒数升序排列经验表键值。"""
    res = {}
    for road_id, dirs in data.items():
        res[road_id] = {}
        for d, times in dirs.items():
            sorted_times = sorted(times.items(), key=lambda x: int(x[0]))
            res[road_id][d] = {k: v for k, v in sorted_times}
    return res


def merge_zhongbiao(old_data: dict, new_data: dict, road_id: str) -> dict:
    """合并旧经验表和新提取的经验点（若同秒数已存在，取车道最大值）。"""
    merged = {k: dict(v) for k, v in old_data.items()}
    for d, times in new_data.items():
        if d not in merged:
            merged[d] = {}
        for t, flow in times.items():
            if t not in merged[d]:
                merged[d][t] = list(flow)
            else:
                merged[d][t] = [
                    max(old_val, new_val)
                    for old_val, new_val in zip(merged[d][t], flow)
                ]
    return merged


def get_cycle_patterns_from_cross_info(road_id: str, cross_info: dict):
    config = cross_info.get(str(road_id), {})
    raw_patterns = config.get("Cycle", [])
    if isinstance(raw_patterns, dict):
        raw_patterns = [raw_patterns]

    patterns = []
    for raw_pattern in raw_patterns:
        if isinstance(raw_pattern, dict):
            raw_pattern = raw_pattern.get("value")
        if isinstance(raw_pattern, list) and raw_pattern:
            patterns.append([str(stage) for stage in raw_pattern])
    patterns.sort(key=len, reverse=True)
    return patterns


def compress_phase_intervals(road_extend):
    layers = []
    current_stage = None
    stage_start = None
    stage_end = None

    for current_time in sorted(road_extend):
        stage = road_extend[current_time]
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


def select_consistent_cycle_group(cycles, target_start, target_end):
    same_pattern_groups = group_consecutive_same_pattern_cycles(cycles)
    all_filtered_groups = []
    total_group_breaks = 0
    total_initial_groups = len(same_pattern_groups)

    for group in same_pattern_groups:
        subgroups = split_cycle_group_on_stage_change(group)
        total_group_breaks += max(0, len(subgroups) - 1)
        valid_subgroups = [
            sub for sub in subgroups if len(sub) >= MIN_CONSECUTIVE_CYCLES
        ]
        all_filtered_groups.extend(valid_subgroups)

    if not all_filtered_groups:
        return [], {
            "status": "rejected_no_qualified_group",
            "initial_groups": total_initial_groups,
            "group_breaks": total_group_breaks,
            "qualified_groups": 0,
        }

    target_center_twice = int(target_start) + int(target_end)
    scored = []
    for group in all_filtered_groups:
        group_center_twice = int(group[0]["start"]) + int(group[-1]["end"])
        distance = abs(group_center_twice - target_center_twice)
        scored.append((distance, int(group[0]["start"]), group))

    best_group = min(scored, key=lambda item: item[:2])[2]
    return best_group, {
        "status": "accepted",
        "initial_groups": total_initial_groups,
        "group_breaks": total_group_breaks,
        "qualified_groups": len(all_filtered_groups),
    }


def select_nearest_three_cycles(cycle_group, target_start, target_end):
    if len(cycle_group) <= MIN_CONSECUTIVE_CYCLES:
        return cycle_group

    target_center_twice = int(target_start) + int(target_end)
    candidates = []
    for idx in range(len(cycle_group) - MIN_CONSECUTIVE_CYCLES + 1):
        window = cycle_group[idx:idx + MIN_CONSECUTIVE_CYCLES]
        center_twice = int(window[0]["start"]) + int(window[-1]["end"])
        candidates.append((
            abs(center_twice - target_center_twice),
            int(window[0]["start"]),
            window,
        ))
    return list(min(candidates, key=lambda item: item[:2])[2])


def calc_direction_time_from_cycles(cycles, road_id, cross_info):
    direction_time = {
        "U": 0, "D": 0, "L": 0, "R": 0,
        "UTL": 0, "DTL": 0, "LTL": 0, "RTL": 0,
    }
    phase_config = cross_info.get(str(road_id), {}).get("phase", {})

    for cycle in cycles:
        for item in cycle["items"]:
            stage_str = str(item["stage"])
            phase_name = str(phase_config.get(stage_str, "")).strip().upper()
            duration = int(item["duration"])
            for target_dir in PHASE_DIRECTION_MAP.get(phase_name, ()):
                direction_time[target_dir] += duration

    return direction_time


def split_flow_by_movement(flow, road_id, cross_info):
    cross_config = cross_info.get(str(road_id), {})
    detector_map = {
        str(k): str(v)
        for k, v in cross_config.get("jtll_ddbh", {}).items()
    }
    lane_maps = cross_config.get("LaneNo", {})

    liuliang = {
        "U": [0] * 10, "D": [0] * 10, "L": [0] * 10, "R": [0] * 10,
        "UTL": [0] * 10, "DTL": [0] * 10, "LTL": [0] * 10, "RTL": [0] * 10,
    }
    stats = Counter()

    for row in flow:
        stats["flow_records"] += 1
        detector_id = str(row.get("jtll_ddbh"))
        direction = detector_map.get(detector_id)
        if direction not in BASE_FLOW_DIRECTIONS:
            stats["unmapped_detector"] += 1
            continue

        try:
            lane = int(row.get("lan"))
        except (TypeError, ValueError):
            stats["invalid_lane_number"] += 1
            continue
        if not 0 <= lane < 10:
            stats["lane_out_of_range"] += 1
            continue

        lane_type = lane_maps.get(direction, {}).get(str(lane), "")
        target_dir = capacity_experience_direction(direction, lane_type)
        if target_dir is None:
            stats["uncontrolled_or_unmapped_movement"] += 1
            continue

        liuliang[target_dir][lane] += 1
        stats["counted_flow"] += 1

    return liuliang, dict(stats)


def jiagong(
    flow,
    phase_intervals,
    road_id,
    cross_info,
    window_start=None,
    window_end=None,
    excluded_directions=None,
):
    if not flow:
        return {"status": "empty_flow"}

    excluded_directions = {
        str(d).upper()
        for d in (excluded_directions or [])
        if str(d).upper() in BASE_FLOW_DIRECTIONS
    }
    patterns = get_cycle_patterns_from_cross_info(road_id, cross_info)
    if not patterns:
        return {"status": "missing_cycle_config"}

    start_time = int(window_start) if window_start is not None else _time_seconds(flow[0]["time"])
    end_time = int(window_end) if window_end is not None else _time_seconds(flow[-1]["time"])

    cycles = find_complete_cycles_from_intervals(
        intervals=phase_intervals,
        patterns=patterns,
        start_time=start_time,
        end_time=end_time,
    )
    initial_count = len(cycles)
    obs_start = start_time
    obs_end = end_time
    expansion_attempted = False
    expansion_dec = cycle_observation_expansion_decision(cycles)

    if expansion_dec["should_expand"]:
        obs_start, obs_end = centered_observation_bounds(start_time, end_time)
        expansion_attempted = True
        cycles = find_complete_cycles_from_intervals(
            intervals=phase_intervals,
            patterns=patterns,
            start_time=obs_start,
            end_time=obs_end,
        )

    if len(cycles) < MIN_CONSECUTIVE_CYCLES:
        return {
            "status": "fewer_than_three_cycles",
            "cycles": len(cycles),
        }

    selected_cycles, cycle_gate = select_consistent_cycle_group(
        cycles,
        target_start=start_time,
        target_end=end_time,
    )
    if not selected_cycles:
        return {
            "status": "no_consistent_same_pattern_cycle_group",
            "cycle_gate": cycle_gate,
        }

    selected_cycles = select_nearest_three_cycles(
        selected_cycles,
        start_time,
        end_time,
    )
    cycles = selected_cycles
    cycle_count = len(cycles)

    direction_time = calc_direction_time_from_cycles(cycles, road_id, cross_info)
    liuliang, flow_stats = split_flow_by_movement(flow, road_id, cross_info)

    zhongbiao = {}
    for d in ("U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL"):
        if d[0] in excluded_directions:
            continue
        avg_green = int(round(direction_time[d] / cycle_count))
        if avg_green > 0:
            zhongbiao[d] = {avg_green: liuliang[d]}

    return {
        "status": "accepted",
        "experience": zhongbiao,
        "cycle_count": cycle_count,
        "flow_stats": flow_stats,
    }


def estimate_capacity_experience(
    *,
    road_ids: list[str],
    dates: list[str],
    logs_dir: str,
    cross_info: dict,
    output_path: str = None,
    reset_output: bool = True,
    verbose: bool = False,
):
    """端到端离线通行能力计算。"""
    road_ids = sorted(str(r) for r in road_ids)
    dates = list(dates)

    experience_data = {} if reset_output or not (output_path and os.path.exists(output_path)) else _load_json(output_path, default={})
    candidate_audit = ExperienceCandidateAudit()
    training_stats = {r: Counter() for r in road_ids}
    daily_stats = {}

    quality_reports_dir = os.path.join(logs_dir, "quality_reports")
    os.makedirs(quality_reports_dir, exist_ok=True)

    for data_day in dates:
        flow_file = os.path.join(logs_dir, "flow", f"{data_day}_flow.txt")
        extend_file = os.path.join(logs_dir, "extend", f"{data_day}_extend.txt")
        quality_report_file = os.path.join(quality_reports_dir, f"{data_day}_quality_report.json")

        clean_flow, clean_extend, quality_report = clean_training_inputs(
            flow_path=flow_file,
            extend_path=extend_file,
            cross_info=cross_info,
            target_cross_ids=road_ids,
            report_path=quality_report_file,
        )

        day_summary = {r: Counter() for r in road_ids}
        daily_stats[data_day] = day_summary

        for road_id in road_ids:
            road_extend = clean_extend.get(road_id, {})
            road_flow = clean_flow.get(road_id, [])
            coverage = quality_report.get("crosses", {}).get(road_id, {}).get("flow_coverage", {})
            excluded_dirs = coverage.get("unavailable_directions", [])

            if not road_extend:
                training_stats[road_id]["missing_stage_data"] += 1
                day_summary[road_id]["missing_stage_data"] += 1
                continue
            if not road_flow:
                training_stats[road_id]["missing_flow_data"] += 1
                day_summary[road_id]["missing_flow_data"] += 1
                continue

            phase_intervals = compress_phase_intervals(road_extend)
            windows = {}
            for row in road_flow:
                row_time = _time_seconds(row["time"])
                w_start = (row_time // WINDOW_SECONDS) * WINDOW_SECONDS
                windows.setdefault(w_start, []).append(row)

            for w_start in sorted(windows):
                res = jiagong(
                    flow=windows[w_start],
                    phase_intervals=phase_intervals,
                    road_id=road_id,
                    cross_info=cross_info,
                    window_start=w_start,
                    window_end=w_start + WINDOW_SECONDS - 1,
                    excluded_directions=excluded_dirs,
                )
                status = res.get("status")
                training_stats[road_id][status] += 1
                day_summary[road_id][status] += 1

                if status == "accepted":
                    candidate_audit.add_experience(
                        road_id=road_id,
                        experience=res["experience"],
                        data_day=data_day,
                        window_start=w_start,
                    )
                    previous = experience_data.get(road_id, {})
                    experience_data[road_id] = merge_zhongbiao(
                        previous,
                        res["experience"],
                        road_id,
                    )

    experience_data = sort_by_time(experience_data)
    if output_path:
        _write_json_atomic(output_path, experience_data)

    audit_report = candidate_audit.build_report()
    training_report = {
        "dates": dates,
        "road_ids": road_ids,
        "training_stats": {r: dict(s) for r, s in training_stats.items()},
        "candidate_audit": audit_report.get("summary", {}),
    }
    return experience_data, training_report
