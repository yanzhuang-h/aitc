"""绿波走廊配置与公开 Python 函数接口。

本模块负责读取、校验和原子保存 ``config/green_wave_corridors.json``，
同时提供绿波配置查询、启停和回放调用函数。它不启动 HTTP 服务，也不直接
向信控机发送方案。
"""

import copy
import json
import os
import re
import tempfile
import threading
from datetime import datetime
from numbers import Real

from . import lvbotest


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
GREEN_WAVE_CONFIG_PATH = os.path.join(
    BASE_DIR,
    "green_wave_corridors.json",
)

DEFAULT_CORRIDOR_ID = "lvbo_01"
_GREEN_WAVE_LOCK = threading.RLock()
_CORRIDOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_DIRECTIONS = ("L", "R", "U", "D")


def _error(reason):
    return {
        "status": "error",
        "saved": False,
        "reason": str(reason),
    }


def _as_int(value, field_name, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise ValueError(f"{field_name} 必须是整数")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} 必须是整数")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field_name} 不能小于 {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field_name} 不能大于 {maximum}")
    return number


def _normalize_time(value, field_name):
    value = str(value or "").strip()
    try:
        datetime.strptime(value, "%H:%M:%S")
    except ValueError:
        raise ValueError(f"{field_name} 必须使用 HH:MM:SS 格式")
    return value


def _read_config_store():
    if not os.path.exists(GREEN_WAVE_CONFIG_PATH):
        return {"version": 1, "corridors": {}}
    with open(GREEN_WAVE_CONFIG_PATH, "r", encoding="utf-8") as config_file:
        data = json.load(config_file)
    if not isinstance(data, dict):
        raise ValueError("绿波配置文件根节点必须是 JSON 对象")
    corridors = data.get("corridors")
    if not isinstance(corridors, dict):
        raise ValueError("绿波配置文件 corridors 必须是 JSON 对象")
    return {
        "version": _as_int(data.get("version", 1), "version", 1),
        "corridors": corridors,
    }


def _write_config_store(data):
    config_dir = os.path.dirname(GREEN_WAVE_CONFIG_PATH)
    os.makedirs(config_dir, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_dir,
            prefix=".green_wave_corridors.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            json.dump(data, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, GREEN_WAVE_CONFIG_PATH)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _normalize_intersections(value, cycle_seconds):
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("intersections 必须是至少包含两个路口的数组")

    normalized = []
    seen = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"intersections[{index}] 必须是 JSON 对象")
        cross_id = str(item.get("cross_id", "")).strip()
        if not cross_id or not cross_id.isdigit():
            raise ValueError(f"intersections[{index}].cross_id 必须是数字字符串")
        if cross_id in seen:
            raise ValueError(f"路口 {cross_id} 在同一走廊内重复")
        seen.add(cross_id)

        green_index = _as_int(
            item.get("green_stage_index", 0),
            f"intersections[{index}].green_stage_index",
            0,
            9,
        )
        balance_index = _as_int(
            item.get("balance_stage_index", 1),
            f"intersections[{index}].balance_stage_index",
            0,
            9,
        )
        if green_index == balance_index:
            raise ValueError(f"路口 {cross_id} 的绿波阶段和补偿阶段不能相同")

        red_seconds = _as_int(
            item.get("default_red_seconds", 0),
            f"intersections[{index}].default_red_seconds",
            0,
        )
        if red_seconds >= cycle_seconds:
            raise ValueError(f"路口 {cross_id} 的默认红灯时间必须小于完整周期")

        normalized.append({
            "cross_id": cross_id,
            "green_stage_index": green_index,
            "balance_stage_index": balance_index,
            "default_red_seconds": red_seconds,
        })
    return normalized


def _normalize_periods(value, intersection_ids):
    if not isinstance(value, list) or not value:
        raise ValueError("periods 必须是非空数组")

    normalized = []
    period_ids = set()
    ranges = []
    expected = set(intersection_ids)
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"periods[{index}] 必须是 JSON 对象")
        period_id = str(item.get("period_id", "")).strip()
        if not period_id or not _CORRIDOR_ID_PATTERN.fullmatch(period_id):
            raise ValueError(f"periods[{index}].period_id 格式无效")
        if period_id in period_ids:
            raise ValueError(f"period_id {period_id} 重复")
        period_ids.add(period_id)

        start_time = _normalize_time(item.get("start_time"), f"periods[{index}].start_time")
        end_time = _normalize_time(item.get("end_time"), f"periods[{index}].end_time")
        start_seconds = _time_to_seconds(start_time)
        end_seconds = _time_to_seconds(end_time)
        if start_seconds >= end_seconds:
            raise ValueError(f"periods[{index}] 暂不支持跨午夜且开始时间必须早于结束时间")
        for old_start, old_end, old_id in ranges:
            if max(start_seconds, old_start) <= min(end_seconds, old_end):
                raise ValueError(f"时间段 {period_id} 与 {old_id} 重叠")
        ranges.append((start_seconds, end_seconds, period_id))

        order = [str(value).strip() for value in item.get("intersection_order", [])]
        if len(order) != len(expected) or set(order) != expected:
            raise ValueError(f"periods[{index}].intersection_order 必须完整包含走廊全部路口")
        if len(order) != len(set(order)):
            raise ValueError(f"periods[{index}].intersection_order 存在重复路口")

        reference = str(item.get("reference_cross_id", "")).strip()
        if reference not in expected:
            raise ValueError(f"periods[{index}].reference_cross_id 不在走廊中")
        if order[0] != reference:
            raise ValueError(f"periods[{index}] 的参考路口必须位于 intersection_order 第一位")

        raw_travel_value = item.get("travel_seconds")
        if not isinstance(raw_travel_value, dict):
            raise ValueError(f"periods[{index}].travel_seconds 必须是 JSON 对象")
        raw_travel = {
            str(cross_id).strip(): travel_value
            for cross_id, travel_value in raw_travel_value.items()
        }
        normalized_travel = {
            str(cross_id): _as_int(
                raw_travel.get(cross_id),
                f"periods[{index}].travel_seconds[{cross_id}]",
                0,
            )
            for cross_id in order
        }
        if set(str(key) for key in raw_travel) != expected:
            raise ValueError(f"periods[{index}].travel_seconds 必须完整覆盖走廊全部路口")
        if normalized_travel[reference] != 0:
            raise ValueError(f"periods[{index}] 的参考路口累计行程时间必须为0")
        ordered_travel = [normalized_travel[cross_id] for cross_id in order]
        if ordered_travel != sorted(ordered_travel) or len(set(ordered_travel)) != len(ordered_travel):
            raise ValueError(f"periods[{index}].travel_seconds 必须沿路口顺序严格递增")

        normalized.append({
            "period_id": period_id,
            "start_time": start_time,
            "end_time": end_time,
            "reference_cross_id": reference,
            "intersection_order": order,
            "travel_seconds": normalized_travel,
        })
    return normalized


def _time_to_seconds(value):
    parsed = datetime.strptime(value, "%H:%M:%S")
    return parsed.hour * 3600 + parsed.minute * 60 + parsed.second


def _normalize_topology(value, intersection_ids):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("topology 必须是 JSON 对象")
    expected = set(intersection_ids)
    normalized = {}
    for cross_id, mapping in value.items():
        cross_key = str(cross_id).strip()
        if cross_key not in expected:
            raise ValueError(f"topology 中的路口 {cross_key} 不在 intersections 中")
        if not isinstance(mapping, dict):
            raise ValueError(f"topology[{cross_key}] 必须是 JSON 对象")
        unknown_directions = {
            str(direction).strip().upper()
            for direction in mapping
        } - set(_DIRECTIONS)
        if unknown_directions:
            raise ValueError(
                f"topology[{cross_key}] 包含无效方向 "
                f"{sorted(unknown_directions)}"
            )
        normalized[cross_key] = {
            direction: str(mapping.get(direction, "")).strip()
            for direction in _DIRECTIONS
        }
    if normalized and set(normalized) != expected:
        missing = sorted(expected - set(normalized))
        raise ValueError(f"topology 缺少走廊路口 {missing}")
    return normalized


def _normalize_road_junction(value, intersection_ids):
    """校验 online 路段到绿波路口方向的映射。"""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("road_junction 必须是 JSON 对象")

    expected = set(intersection_ids)
    normalized = {}
    mapped_cross_ids = set()
    for raw_rid, mapping in value.items():
        rid = str(raw_rid).strip()
        if not rid:
            raise ValueError("road_junction 中的 rid 不能为空")
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(f"road_junction[{rid}] 必须是非空 JSON 对象")

        direction_map = {}
        for raw_direction, raw_cross_id in mapping.items():
            direction = str(raw_direction).strip().upper()
            if direction not in _DIRECTIONS:
                raise ValueError(
                    f"road_junction[{rid}] 的方向 {raw_direction} 无效，"
                    "只允许 L/R/U/D"
                )
            cross_id = str(raw_cross_id).strip()
            if cross_id not in expected:
                raise ValueError(
                    f"road_junction[{rid}][{direction}] 的路口 {cross_id} "
                    "不在 intersections 中"
                )
            direction_map[direction] = cross_id
            mapped_cross_ids.add(cross_id)
        normalized[rid] = direction_map
    if normalized and mapped_cross_ids != expected:
        missing = sorted(expected - mapped_cross_ids)
        raise ValueError(f"road_junction 缺少走廊路口 {missing} 的路段映射")
    return normalized


def _normalize_corridor(value, corridor_id=None):
    if not isinstance(value, dict):
        raise ValueError("corridor 必须是 JSON 对象")
    normalized_id = str(corridor_id or value.get("corridor_id", "")).strip()
    if not normalized_id or not _CORRIDOR_ID_PATTERN.fullmatch(normalized_id):
        raise ValueError("corridor_id 只能包含字母、数字、点、下划线和连字符")

    cycle_seconds = _as_int(value.get("cycle_seconds", 90), "cycle_seconds", 30, 600)
    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是 bool")

    intersections = _normalize_intersections(value.get("intersections"), cycle_seconds)
    intersection_ids = [item["cross_id"] for item in intersections]
    periods = _normalize_periods(value.get("periods"), intersection_ids)

    minimum_remaining = _as_int(
        value.get("minimum_remaining_green_seconds", 10),
        "minimum_remaining_green_seconds",
        0,
        cycle_seconds,
    )
    target_elapsed = _as_int(
        value.get("simulation_target_elapsed_green_seconds", 10),
        "simulation_target_elapsed_green_seconds",
        0,
        cycle_seconds,
    )
    cooldown_seconds = _as_int(
        value.get("cooldown_seconds", max(1, cycle_seconds - 5)),
        "cooldown_seconds",
        0,
        cycle_seconds,
    )

    return {
        "corridor_id": normalized_id,
        "name": str(value.get("name", normalized_id)).strip() or normalized_id,
        "enabled": enabled,
        "cycle_seconds": cycle_seconds,
        "offset_step_seconds": _as_int(
            value.get("offset_step_seconds", 3),
            "offset_step_seconds",
            1,
            cycle_seconds,
        ),
        "minimum_remaining_green_seconds": minimum_remaining,
        "simulation_target_elapsed_green_seconds": target_elapsed,
        "cooldown_seconds": cooldown_seconds,
        "intersections": intersections,
        "periods": periods,
        "road_junction": _normalize_road_junction(
            value.get("road_junction"),
            intersection_ids,
        ),
        "topology": _normalize_topology(
            value.get("topology"),
            intersection_ids,
        ),
    }


def _normalized_corridor_map(store):
    normalized = {}
    for corridor_id, corridor in store["corridors"].items():
        item = _normalize_corridor(corridor, corridor_id)
        normalized[item["corridor_id"]] = item
    _validate_enabled_conflicts(normalized)
    return normalized


def _validate_enabled_conflicts(corridors):
    owner_map = {}
    for corridor_id, corridor in corridors.items():
        if not corridor.get("enabled"):
            continue
        for item in corridor["intersections"]:
            cross_id = item["cross_id"]
            old_owner = owner_map.get(cross_id)
            if old_owner is not None:
                raise ValueError(
                    f"启用走廊 {corridor_id} 与 {old_owner} 共用路口 {cross_id}"
                )
            owner_map[cross_id] = corridor_id


def load_green_wave_corridors():
    """供项目内部调用：每次从 JSON 读取全部已校验走廊。"""
    with _GREEN_WAVE_LOCK:
        return copy.deepcopy(_normalized_corridor_map(_read_config_store()))


def load_enabled_green_wave_corridors():
    """供全局协调调用：读取所有启用走廊，保存后下一轮立即生效。"""
    return [
        corridor
        for corridor in load_green_wave_corridors().values()
        if corridor.get("enabled")
    ]


def _get_corridor_or_raise(corridor_id):
    corridor_key = str(corridor_id or DEFAULT_CORRIDOR_ID).strip()
    corridors = load_green_wave_corridors()
    if corridor_key not in corridors:
        raise LookupError(f"corridor_id {corridor_key} 不存在")
    return corridors[corridor_key]


def list_green_wave_corridors(payload):
    """列出全部绿波走廊。"""
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是 dict")
        corridors = load_green_wave_corridors()
        return {
            "status": "success",
            "saved": False,
            "operation": "listed",
            "items": [copy.deepcopy(corridor) for corridor in corridors.values()],
        }
    except (LookupError, ValueError) as error:
        return _error(error)
    except Exception as error:
        return _error(f"读取绿波走廊失败: {error}")


def get_green_wave_corridor_config(payload):
    """查询一条绿波走廊完整配置。"""
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是 dict")
        corridor = _get_corridor_or_raise(payload.get("corridor_id"))
        return {
            "status": "success",
            "saved": False,
            "operation": "queried",
            "corridor": copy.deepcopy(corridor),
        }
    except (LookupError, ValueError) as error:
        return _error(error)
    except Exception as error:
        return _error(f"查询绿波走廊失败: {error}")


def save_green_wave_corridor_config(payload):
    """校验并新增或更新一条绿波走廊。"""
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是 dict")
        dry_run = payload.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise ValueError("dry_run 必须是 bool")
        normalized = _normalize_corridor(payload.get("corridor"))

        with _GREEN_WAVE_LOCK:
            store = _read_config_store()
            corridors = _normalized_corridor_map(store)
            operation = "updated" if normalized["corridor_id"] in corridors else "created"
            corridors[normalized["corridor_id"]] = normalized
            _validate_enabled_conflicts(corridors)
            if not dry_run:
                store["corridors"] = corridors
                _write_config_store(store)
                lvbotest.reset_green_wave_state(normalized["corridor_id"])

        return {
            "status": "validated" if dry_run else "success",
            "saved": not dry_run,
            "operation": operation,
            "corridor_id": normalized["corridor_id"],
            "corridor": copy.deepcopy(normalized),
        }
    except (LookupError, ValueError) as error:
        return _error(error)
    except Exception as error:
        return _error(f"保存绿波走廊失败: {error}")


def set_green_wave_corridor_enabled(payload):
    """启用或停用一条走廊，不删除原配置。"""
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是 dict")
        corridor_id = str(payload.get("corridor_id", "")).strip()
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("enabled 必须是 bool")

        with _GREEN_WAVE_LOCK:
            store = _read_config_store()
            corridors = _normalized_corridor_map(store)
            if corridor_id not in corridors:
                raise LookupError(f"corridor_id {corridor_id} 不存在")
            corridors[corridor_id]["enabled"] = enabled
            _validate_enabled_conflicts(corridors)
            store["corridors"] = corridors
            _write_config_store(store)
            lvbotest.reset_green_wave_state(corridor_id)

        return {
            "status": "success",
            "saved": True,
            "operation": "enabled" if enabled else "disabled",
            "corridor_id": corridor_id,
            "enabled": enabled,
        }
    except (LookupError, ValueError) as error:
        return _error(error)
    except Exception as error:
        return _error(f"更新绿波走廊状态失败: {error}")


def query_green_wave_config(payload):
    """兼容原查询函数，返回指定走廊配置。"""
    result = get_green_wave_corridor_config(payload)
    if result.get("status") != "success":
        return result
    corridor = result["corridor"]
    result.update({
        "corridor_id": corridor["corridor_id"],
        "cycle_seconds": corridor["cycle_seconds"],
        "minimum_remaining_green_seconds": corridor["minimum_remaining_green_seconds"],
        "offset_step_seconds": corridor["offset_step_seconds"],
        "intersection_order": [
            item["cross_id"] for item in corridor["intersections"]
        ],
        "default_red_durations": {
            item["cross_id"]: item["default_red_seconds"]
            for item in corridor["intersections"]
        },
        "periods": copy.deepcopy(corridor["periods"]),
    })
    for period in corridor["periods"]:
        result[period["period_id"]] = {
            "time_range": f"{period['start_time']}-{period['end_time']}",
            "reference": period["reference_cross_id"],
            "travel_seconds": copy.deepcopy(period["travel_seconds"]),
        }
    return result


def _normalize_timestamp(value):
    if isinstance(value, bool):
        raise ValueError("timestamp 必须为有效的秒级或毫秒级时间戳")
    if not isinstance(value, Real):
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError("timestamp 必须为有效的秒级或毫秒级时间戳")
    timestamp = int(value)
    if timestamp >= 10_000_000_000:
        timestamp //= 1000
    if timestamp <= 0:
        raise ValueError("timestamp 必须为有效的秒级或毫秒级时间戳")
    try:
        datetime.fromtimestamp(timestamp)
    except (OverflowError, OSError, ValueError):
        raise ValueError("timestamp 超出系统支持范围")
    return timestamp


def _normalize_plans(value, corridor):
    if not isinstance(value, dict):
        raise ValueError("plans 必须是包含走廊全部路口的 dict")
    order = [item["cross_id"] for item in corridor["intersections"]]
    missing = [rid for rid in order if rid not in value]
    if missing:
        raise ValueError(f"plans 缺少绿波路口 {', '.join(missing)}")

    plans = {}
    for rid in order:
        plan = value.get(rid)
        if not isinstance(plan, list) or len(plan) < 10:
            raise ValueError(f"plans[{rid}] 必须是长度至少为10的 list")
        normalized = []
        for index, item in enumerate(plan[:10]):
            if isinstance(item, bool) or not isinstance(item, Real):
                raise ValueError(f"plans[{rid}][{index}] 必须是数字")
            normalized.append(int(round(item)))
        plans[rid] = normalized
    return plans


def _build_cycle_report(plans, corridor):
    report = {}
    all_aligned = True
    for item in corridor["intersections"]:
        rid = item["cross_id"]
        plan = plans[rid]
        p1 = int(plan[item["green_stage_index"]])
        p2 = int(plan[item["balance_stage_index"]])
        red_seconds = int(item["default_red_seconds"])
        complete_cycle = p1 + p2 + red_seconds
        aligned = abs(complete_cycle - corridor["cycle_seconds"]) <= 1
        all_aligned = all_aligned and aligned
        report[rid] = {
            "green_stage_seconds": p1,
            "balance_stage_seconds": p2,
            "red_seconds": red_seconds,
            "complete_cycle_seconds": complete_cycle,
            "aligned": aligned,
        }
    return report, all_aligned


def reset_green_wave_session(payload):
    """重置指定走廊在当前进程内的协调状态。"""
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是 dict")
        corridor = _get_corridor_or_raise(payload.get("corridor_id"))
        with _GREEN_WAVE_LOCK:
            lvbotest.reset_green_wave_state(corridor["corridor_id"])
        return {
            "status": "success",
            "saved": False,
            "operation": "reset",
            "corridor_id": corridor["corridor_id"],
            "message": "绿波运行状态已重置",
        }
    except (LookupError, ValueError) as error:
        return _error(error)
    except Exception as error:
        return _error(f"重置绿波状态失败: {error}")


def simulate_green_wave(payload):
    """执行指定走廊的一轮 online 回放并返回结构化结果。"""
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是 dict")
        corridor = _get_corridor_or_raise(payload.get("corridor_id"))
        timestamp = _normalize_timestamp(payload.get("timestamp"))
        plans_before = _normalize_plans(payload.get("plans"), corridor)
        reset_requested = payload.get("reset", False)
        if not isinstance(reset_requested, bool):
            raise ValueError("reset 必须是 bool")

        time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        algorithm_report = {}
        working_result = copy.deepcopy(plans_before)
        with _GREEN_WAVE_LOCK:
            if reset_requested:
                lvbotest.reset_green_wave_state(corridor["corridor_id"])
            plans_after = lvbotest.apply_green_wave_coordination(
                time_str=time_str,
                cur_action_map=copy.deepcopy(plans_before),
                result_action_map=working_result,
                coordinate_map_set={},
                extend_map=None,
                simulation_mode=True,
                simulation_timestamp=timestamp,
                report_out=algorithm_report,
                corridor_config=corridor,
            )

        order = [item["cross_id"] for item in corridor["intersections"]]
        plans_after = {rid: list(plans_after[rid][:10]) for rid in order}
        cycle_report, cycle_aligned = _build_cycle_report(plans_after, corridor)
        green_band_aligned = bool(algorithm_report.get("green_band_aligned", False))
        final_aligned = bool(cycle_aligned and green_band_aligned)
        if algorithm_report.get("peak") == "none":
            message = "当前不在绿波启用时段"
        elif not cycle_aligned:
            failed = [rid for rid, item in cycle_report.items() if not item["aligned"]]
            message = f"路口 {', '.join(failed)} 周期未达到{corridor['cycle_seconds']}秒"
        elif not green_band_aligned:
            message = algorithm_report.get("message") or "绿灯窗口尚未达标"
        else:
            message = "周期和车辆到达绿灯窗口均已达标"

        return {
            "status": "success",
            "saved": False,
            "operation": "simulated",
            "corridor_id": corridor["corridor_id"],
            "test_timestamp": timestamp,
            "test_time": time_str,
            "peak": algorithm_report.get("peak", "none"),
            "reset_applied": reset_requested,
            "plans_before": copy.deepcopy(plans_before),
            "plans_after": copy.deepcopy(plans_after),
            "cycle_report": cycle_report,
            "cycle_aligned": cycle_aligned,
            "green_band_aligned": green_band_aligned,
            "final_aligned": final_aligned,
            "target_offset_map": copy.deepcopy(algorithm_report.get("target_offset_map", {})),
            "target_start_map": copy.deepcopy(algorithm_report.get("target_start_map", {})),
            "current_offset_map": copy.deepcopy(algorithm_report.get("current_offset_map", {})),
            "arrival_report": copy.deepcopy(algorithm_report.get("arrival_report", {})),
            "message": message,
        }
    except (LookupError, ValueError) as error:
        return _error(error)
    except Exception as error:
        return _error(f"绿波模拟失败: {error}")


__all__ = [
    "load_green_wave_corridors",
    "load_enabled_green_wave_corridors",
    "list_green_wave_corridors",
    "get_green_wave_corridor_config",
    "save_green_wave_corridor_config",
    "set_green_wave_corridor_enabled",
    "query_green_wave_config",
    "simulate_green_wave",
    "reset_green_wave_session",
]
