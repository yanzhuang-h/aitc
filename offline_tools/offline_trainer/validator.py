"""独立离线训练模块 - 经验表结构验证与无损合并器 (Validator & Merger).

负责校验补全后的经验表是否符合 cross_info 拓扑规范，
以及在交付阶段将目标路口无损合并入生产底表 (offline_experience.json)。
完全独立，零外部依赖，仅基于 Python 标准库。
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .lane_policy import (
    BASE_DIRECTIONS,
    LANE_COUNT,
    configured_movement_lane_policy,
    policy_metadata,
)

VALID_DIRECTIONS = {
    "U", "D", "L", "R",
    "UTL", "DTL", "LTL", "RTL",
}
MIN_GREEN_TIME = 1
MAX_GREEN_TIME = 150


class ExperienceValidationError(Exception):
    """经验表校验异常。"""
    pass


def _normalize_vector(flow):
    if not isinstance(flow, (list, tuple)):
        raise TypeError("flow vector must be a list or tuple")
    values = [int(v) for v in flow]
    if len(values) != LANE_COUNT:
        raise ValueError(f"flow vector length must be {LANE_COUNT}, got {len(values)}")
    if any(v < 0 for v in values):
        raise ValueError("flow values must be non-negative")
    return values


def _configured_lane_sets(cross_config, direction):
    base_direction = direction[0]
    base_policy = configured_movement_lane_policy(cross_config, base_direction)
    left_policy = configured_movement_lane_policy(
        cross_config,
        base_direction + "TL",
    )
    return base_policy["eligible"], left_policy["eligible"]


def validate_experience_table(
    table: dict,
    cross_info: Optional[dict] = None,
    required_road_ids: Optional[Sequence[str]] = None,
    allow_legacy_records: bool = False,
) -> Dict[str, Any]:
    """验证经验表结构、方向、绿灯范围与车道有效性。"""
    errors: List[str] = []
    warnings: List[str] = []
    summary = {
        "roads": 0,
        "directions": 0,
        "points": 0,
        "nonzero_lane_values": 0,
    }

    if not isinstance(table, dict) or not table:
        errors.append("经验表必须是非空字典对象")
        return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}

    required_road_ids_set = {str(item) for item in (required_road_ids or [])}
    missing_roads = sorted(required_road_ids_set - set(map(str, table)))
    if missing_roads:
        errors.append(f"缺少必要路口: {','.join(missing_roads)}")

    for raw_road_id, road_data in table.items():
        road_id = str(raw_road_id)
        summary["roads"] += 1
        if not isinstance(road_data, dict) or not road_data:
            errors.append(f"{road_id}: 路口数据为空或格式非法")
            continue

        cross_config = None
        if cross_info is not None:
            cross_config = cross_info.get(road_id)
            if not isinstance(cross_config, dict):
                errors.append(f"{road_id}: cross_info.json 中缺少该路口配置")
                continue

        for direction, time_map in road_data.items():
            summary["directions"] += 1
            if direction not in VALID_DIRECTIONS:
                errors.append(f"{road_id}/{direction}: 非法方向")
                continue
            if not isinstance(time_map, dict) or not time_map:
                errors.append(f"{road_id}/{direction}: 方向下无绿灯秒数点")
                continue

            allowed_lanes = None
            if cross_config is not None:
                base_lanes, left_lanes = _configured_lane_sets(cross_config, direction)
                allowed_lanes = left_lanes if direction.endswith("TL") else base_lanes
                if direction.endswith("TL") and not left_lanes:
                    message = f"{road_id}/{direction}: 未配置 1A 专用左转车道"
                    (warnings if allow_legacy_records else errors).append(message)
                elif not allowed_lanes:
                    message = f"{road_id}/{direction}: 未配置受控通行能力车道"
                    (warnings if allow_legacy_records else errors).append(message)

            for raw_green_time, vector in time_map.items():
                try:
                    green_time = int(raw_green_time)
                except (TypeError, ValueError):
                    errors.append(f"{road_id}/{direction}/{raw_green_time}: 非法绿灯时长")
                    continue
                if not MIN_GREEN_TIME <= green_time <= MAX_GREEN_TIME:
                    message = f"{road_id}/{direction}/{green_time}: 绿灯时长超出 1..150 范围"
                    if allow_legacy_records and green_time == 0:
                        warnings.append(message + " (旧版占位符已忽略)")
                    else:
                        errors.append(message)
                    continue

                try:
                    normalized = _normalize_vector(vector)
                except (TypeError, ValueError) as error:
                    errors.append(f"{road_id}/{direction}/{green_time}: {error}")
                    continue

                if allowed_lanes is not None:
                    invalid_nonzero_lanes = [
                        str(index)
                        for index, value in enumerate(normalized)
                        if value > 0 and index not in allowed_lanes
                    ]
                    if invalid_nonzero_lanes:
                        message = (
                            f"{road_id}/{direction}/{green_time}: 非受控车道存在非零流量 "
                            f"{','.join(invalid_nonzero_lanes)}"
                        )
                        (warnings if allow_legacy_records else errors).append(message)

                summary["points"] += 1
                summary["nonzero_lane_values"] += sum(1 for v in normalized if v > 0)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
        "lane_policy": policy_metadata(),
    }


def merge_experience_tables(
    active_table: dict,
    candidate_table: dict,
    replace_road_ids: Optional[Sequence[str]] = None,
) -> Tuple[dict, List[str]]:
    """无损合并：仅更新或追加 candidate_table 中的路口，绝不误删 active_table 中的存量生产路口。"""
    result = copy.deepcopy(active_table or {})
    replace_road_ids_set = {str(item) for item in (replace_road_ids or [])}
    updated_roads: List[str] = []

    for raw_road_id, candidate_road in (candidate_table or {}).items():
        road_id = str(raw_road_id)
        updated_roads.append(road_id)
        if road_id in replace_road_ids_set:
            result[road_id] = copy.deepcopy(candidate_road)
            continue
        result.setdefault(road_id, {})
        for direction, time_map in candidate_road.items():
            result[road_id][direction] = copy.deepcopy(time_map)

    return result, sorted(updated_roads)
