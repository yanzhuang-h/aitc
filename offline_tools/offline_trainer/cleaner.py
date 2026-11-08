"""独立离线训练模块 - 原始日志清洗 (Cleaner).

解析 flow 和 extend 原始文本日志，过滤异常秒数跳变与脏数据。
完全独立，零外部依赖，仅基于 Python 标准库。
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter, defaultdict

from .lane_policy import (
    BASE_DIRECTIONS,
    classify_lane_type,
    is_dedicated_left,
    policy_metadata,
)

DEFAULT_MAX_STAGE_GAP_SECONDS = 3


def _time_seconds(value):
    value = int(value)
    if value > 10_000_000_000:
        value //= 1000
    if value <= 0:
        raise ValueError("timestamp must be positive")
    return value


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


def _build_detector_index(cross_info, target_cross_ids):
    detector_candidates = defaultdict(list)
    for cross_id in target_cross_ids:
        config = cross_info.get(cross_id, {})
        for detector_id, direction in config.get("jtll_ddbh", {}).items():
            detector_candidates[str(detector_id)].append((cross_id, str(direction)))

    detector_index = {}
    ambiguous = {}
    for detector_id, candidates in detector_candidates.items():
        if len(candidates) == 1:
            detector_index[detector_id] = candidates[0]
        else:
            cross_ids = sorted({candidate[0] for candidate in candidates})
            ambiguous[detector_id] = cross_ids

    known_detector_ids = set()
    for config in cross_info.values():
        for detector_id in config.get("jtll_ddbh", {}):
            known_detector_ids.add(str(detector_id))

    return detector_index, ambiguous, known_detector_ids


def _init_cross_reports(target_cross_ids):
    reports = {}
    for cross_id in target_cross_ids:
        reports[cross_id] = {
            "flow": Counter(),
            "extend": Counter(),
            "flow_distribution": {
                "detectors": Counter(),
                "directions": Counter(),
                "lanes": Counter(),
                "movements": Counter(),
            },
            "flow_coverage": {
                "total_flow_records": 0,
                "first_flow_timestamp": None,
                "last_flow_timestamp": None,
                "missing_flow_seconds": 0,
                "active_directions": [],
                "configured_directions": [],
                "unavailable_directions": [],
                "coverage_ratio": 0.0,
            },
            "stage_coverage": {
                "total_seconds": 0,
                "observed_seconds": 0,
                "interpolated_seconds": 0,
                "unknown_seconds": 0,
                "conflicting_seconds": 0,
                "coverage_ratio": 0.0,
            },
        }
    return reports


def _clean_flow(
    flow_path,
    cross_info,
    detector_index,
    ambiguous,
    known_detector_ids,
    cross_reports,
):
    clean_flow = defaultdict(list)
    seen = set()
    totals = Counter()

    with open(flow_path, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            totals["lines"] += 1
            try:
                row = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                totals["invalid_json"] += 1
                continue

            try:
                detector_id = str(row["jtll_ddbh"])
                raw_timestamp = int(row["ts"])
                timestamp = _time_seconds(raw_timestamp)
                lane = int(row["ycsb_cdbh"])
            except (KeyError, TypeError, ValueError):
                totals["invalid_required_fields"] += 1
                continue

            if detector_id in ambiguous:
                totals["ambiguous_detector"] += 1
                continue
            mapping = detector_index.get(detector_id)
            if mapping is None:
                if detector_id in known_detector_ids:
                    totals["outside_target"] += 1
                else:
                    totals["unmapped_detector"] += 1
                continue

            cross_id, direction = mapping
            report = cross_reports[cross_id]["flow"]
            report["mapped"] += 1
            lane_map = cross_info[cross_id].get("LaneNo", {}).get(direction, {})
            lane_key = str(lane)
            if lane_key not in lane_map:
                report["invalid_lane"] += 1
                totals["invalid_lane"] += 1
                continue

            movement = row.get("ycsb_xsfx")
            if movement is not None:
                movement = str(movement).strip()
            expected_movement = lane_map.get(lane_key)
            if expected_movement:
                expected_movement = str(expected_movement).strip()

            movement_is_left = is_dedicated_left(movement)
            expected_is_left = is_dedicated_left(expected_movement)
            if movement and expected_movement and movement != expected_movement:
                if movement_is_left or expected_is_left:
                    report["dedicated_left_movement_mismatch"] += 1
                    totals["dedicated_left_movement_mismatch"] += 1
                    continue
                report["non_left_movement_mismatch_accepted"] += 1
                totals["non_left_movement_mismatch_accepted"] += 1

            event_key = (detector_id, raw_timestamp, lane, movement)
            if event_key in seen:
                report["duplicate"] += 1
                totals["duplicate"] += 1
                continue
            seen.add(event_key)

            clean_flow[cross_id].append({
                "CrossId": cross_id,
                "time": str(raw_timestamp),
                "jtll_ddbh": detector_id,
                "lan": lane,
                "ycsb_xsfx": movement,
            })
            distribution = cross_reports[cross_id]["flow_distribution"]
            distribution["detectors"][detector_id] += 1
            distribution["directions"][direction] += 1
            distribution["lanes"][f"{direction}:{lane}"] += 1
            distribution["movements"][
                movement or expected_movement or "<empty>"
            ] += 1
            report["accepted"] += 1
            totals["accepted"] += 1

    for rows in clean_flow.values():
        rows.sort(key=lambda row: _time_seconds(row["time"]))
    return dict(clean_flow), totals


def _clean_extend(
    extend_path,
    cross_info,
    target_cross_ids,
    cross_reports,
    max_stage_gap_seconds,
):
    observed = defaultdict(dict)
    conflicts = defaultdict(set)
    totals = Counter()

    with open(extend_path, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            totals["lines"] += 1
            try:
                row = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                totals["invalid_json"] += 1
                continue

            try:
                cross_id = str(row["CrossId"])
                timestamp = _time_seconds(row["time"])
                stage = str(row["curStageNo"])
            except (KeyError, TypeError, ValueError):
                totals["invalid_required_fields"] += 1
                continue

            if cross_id not in target_cross_ids:
                totals["outside_target"] += 1
                continue

            report = cross_reports[cross_id]["extend"]
            report["target_records"] += 1
            valid_stages = {str(key) for key in cross_info[cross_id].get("phase", {})}
            if stage == "-1":
                report["explicit_minus_one"] += 1
                totals["explicit_minus_one"] += 1
            elif stage not in valid_stages:
                report["invalid_stage"] += 1
                totals["invalid_stage"] += 1
                stage = "-1"

            previous = observed[cross_id].get(timestamp)
            if previous is not None:
                if previous == stage:
                    report["duplicate"] += 1
                    totals["duplicate"] += 1
                    continue
                conflicts[cross_id].add(timestamp)
                report["conflicting_second"] += 1
                totals["conflicting_second"] += 1
                observed[cross_id][timestamp] = "-1"
                continue

            observed[cross_id][timestamp] = stage
            report["accepted"] += 1
            totals["accepted"] += 1

    continuous_extend = {}
    for cross_id in target_cross_ids:
        cross_observed = observed.get(cross_id, {})
        cross_conflicts = conflicts.get(cross_id, set())
        stats = cross_reports[cross_id]["stage_coverage"]
        if not cross_observed:
            continuous_extend[cross_id] = {}
            continue

        timestamps = sorted(cross_observed.keys())
        first_time = timestamps[0]
        last_time = timestamps[-1]
        stats["total_seconds"] = last_time - first_time + 1
        stats["conflicting_seconds"] = len(cross_conflicts)

        filled = {}
        last_known_stage = "-1"
        gap_count = 0

        for current_time in range(first_time, last_time + 1):
            raw_stage = cross_observed.get(current_time)
            if raw_stage is not None:
                filled[current_time] = raw_stage
                stats["observed_seconds"] += 1
                last_known_stage = raw_stage
                gap_count = 0
            else:
                gap_count += 1
                if (
                    last_known_stage != "-1"
                    and gap_count <= max_stage_gap_seconds
                ):
                    filled[current_time] = last_known_stage
                    stats["interpolated_seconds"] += 1
                else:
                    filled[current_time] = "-1"
                    stats["unknown_seconds"] += 1

        continuous_extend[cross_id] = filled
        if stats["total_seconds"] > 0:
            usable = stats["observed_seconds"] + stats["interpolated_seconds"]
            stats["coverage_ratio"] = round(usable / stats["total_seconds"], 4)

    return continuous_extend, totals


def _populate_flow_coverage(cross_info, clean_flow, cross_reports):
    for cross_id, report in cross_reports.items():
        flow_rows = clean_flow.get(cross_id, [])
        coverage = report["flow_coverage"]
        lane_map = cross_info.get(cross_id, {}).get("LaneNo", {})
        configured = [
            direction
            for direction in BASE_DIRECTIONS
            if direction in lane_map and lane_map[direction]
        ]
        coverage["configured_directions"] = sorted(configured)
        coverage["total_flow_records"] = len(flow_rows)

        if not flow_rows:
            coverage["unavailable_directions"] = sorted(configured)
            continue

        timestamps = [
            _time_seconds(row["time"])
            for row in flow_rows
        ]
        first_time = min(timestamps)
        last_time = max(timestamps)
        distinct_seconds = len(set(timestamps))
        total_seconds = last_time - first_time + 1

        coverage["first_flow_timestamp"] = first_time
        coverage["last_flow_timestamp"] = last_time
        coverage["missing_flow_seconds"] = max(0, total_seconds - distinct_seconds)
        coverage["coverage_ratio"] = (
            round(distinct_seconds / total_seconds, 4)
            if total_seconds > 0
            else 0.0
        )

        direction_counts = report["flow_distribution"]["directions"]
        active = [
            direction
            for direction, count in direction_counts.items()
            if count > 0
        ]
        coverage["active_directions"] = sorted(active)
        coverage["unavailable_directions"] = sorted(
            set(configured) - set(active)
        )


def clean_training_inputs(
    flow_path,
    extend_path,
    cross_info,
    target_cross_ids=None,
    max_stage_gap_seconds=DEFAULT_MAX_STAGE_GAP_SECONDS,
    report_path=None,
):
    """清洗流量与信控数据，返回 clean_flow, clean_extend, quality_report。"""
    if target_cross_ids is None:
        target_cross_ids = set(cross_info)
    else:
        target_cross_ids = {str(cross_id) for cross_id in target_cross_ids}

    detector_index, ambiguous, known_detectors = _build_detector_index(
        cross_info, target_cross_ids
    )
    cross_reports = _init_cross_reports(target_cross_ids)

    clean_flow, flow_totals = _clean_flow(
        flow_path,
        cross_info,
        detector_index,
        ambiguous,
        known_detectors,
        cross_reports,
    )
    clean_extend, extend_totals = _clean_extend(
        extend_path,
        cross_info,
        target_cross_ids,
        cross_reports,
        max_stage_gap_seconds,
    )
    _populate_flow_coverage(cross_info, clean_flow, cross_reports)

    report = {
        "totals": {
            "flow": dict(flow_totals),
            "extend": dict(extend_totals),
        },
        "ambiguous_detectors": ambiguous,
        "lane_policy": policy_metadata(),
        "crosses": {
            cross_id: {
                "flow": dict(cross_reports[cross_id]["flow"]),
                "extend": dict(cross_reports[cross_id]["extend"]),
                "flow_distribution": {
                    key: dict(counter)
                    for key, counter in cross_reports[cross_id][
                        "flow_distribution"
                    ].items()
                },
                "flow_coverage": cross_reports[cross_id]["flow_coverage"],
                "stage_coverage": cross_reports[cross_id]["stage_coverage"],
            }
            for cross_id in sorted(target_cross_ids)
        },
    }
    if report_path:
        _write_json_atomic(report_path, report)
    return clean_flow, clean_extend, report


def clean_stage_inputs(
    extend_path,
    cross_info,
    target_cross_ids=None,
    max_stage_gap_seconds=DEFAULT_MAX_STAGE_GAP_SECONDS,
    report_path=None,
):
    """单独清洗阶段数据。"""
    if target_cross_ids is None:
        target_cross_ids = set(cross_info)
    else:
        target_cross_ids = {str(cross_id) for cross_id in target_cross_ids}

    cross_reports = _init_cross_reports(target_cross_ids)
    clean_extend, extend_totals = _clean_extend(
        extend_path,
        cross_info,
        target_cross_ids,
        cross_reports,
        max_stage_gap_seconds,
    )
    report = {
        "totals": {"extend": dict(extend_totals)},
        "crosses": {
            cross_id: {
                "extend": dict(cross_reports[cross_id]["extend"]),
                "stage_coverage": cross_reports[cross_id]["stage_coverage"],
            }
            for cross_id in sorted(target_cross_ids)
        },
    }
    if report_path:
        _write_json_atomic(report_path, report)
    return clean_extend, report
