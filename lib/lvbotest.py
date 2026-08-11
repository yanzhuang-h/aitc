from collections import defaultdict
from copy import deepcopy
import copy
import statistics
from typing import Dict, List, Optional, Union
from datetime import datetime
import time

# --------------------------------------动态绿波配置-------------------------------------
OFFSET_STEP = 3
OFFSET_TOLERANCE = 1
GREEN_BAND_OBSERVATION_CYCLES = 3
GREEN_BAND_MIN_REMAIN_SECONDS = 10
SIMULATION_TARGET_ELAPSED_GREEN_SECONDS = 10
MAX_TIMING_MATCH_ERROR_SECONDS = 45
DEFAULT_CORRIDOR_CYCLE = 90
DEFAULT_RED_DURATIONS = {}
COOLDOWN_SECONDS = 85
GREEN_STAGE_INDEX_MAP = {}
BALANCE_STAGE_INDEX_MAP = {}
PERIOD_CONFIG_MAP = {}

# --------------------------------------绿波控制全局状态-------------------------------------
ORDER = []
start = False
cycle_green = False
offset_green = False
cycle_done = False
offset_done = False
cnt = 0
fix_plan = None
direction = ""
green_plan_map = {}
last_green_wave_send_time = 0
# 仅用于 online 回放测试：记录各路口在虚拟周期中的阶段 1 起点。
# online 数据不含信控机阶段反馈，不能据此还原真实起绿时刻。
simulation_offset_map = {}
# 仅用于 online 回放测试：记录尚未完成的虚拟阶段 1 目标起点。
# 目标起点与阶段时长分离，避免为了移动相位而持续拉长 P1、压缩 P2。
simulation_target_start_map = {}
_ACTIVE_CORRIDOR_ID = ""
_ACTIVE_CORRIDOR_CONFIG = None
_GREEN_WAVE_STATE_MAP = {}
_GREEN_WAVE_CONFIG_MAP = {}


def _stage_indices(rid):
    return (
        int(GREEN_STAGE_INDEX_MAP.get(str(rid), 0)),
        int(BALANCE_STAGE_INDEX_MAP.get(str(rid), 1)),
    )


def _empty_state():
    return {
        "start": False,
        "cycle_green": False,
        "offset_green": False,
        "cycle_done": False,
        "offset_done": False,
        "cnt": 0,
        "fix_plan": None,
        "direction": "",
        "green_plan_map": {},
        "last_green_wave_send_time": 0,
        "simulation_offset_map": {},
        "simulation_target_start_map": {},
    }


def _capture_active_state():
    return {
        "start": bool(start),
        "cycle_green": bool(cycle_green),
        "offset_green": bool(offset_green),
        "cycle_done": bool(cycle_done),
        "offset_done": bool(offset_done),
        "cnt": int(cnt),
        "fix_plan": copy.deepcopy(fix_plan),
        "direction": str(direction),
        "green_plan_map": copy.deepcopy(green_plan_map),
        "last_green_wave_send_time": last_green_wave_send_time,
        "simulation_offset_map": copy.deepcopy(simulation_offset_map),
        "simulation_target_start_map": copy.deepcopy(simulation_target_start_map),
    }


def _restore_active_state(state_value):
    global start, cycle_green, offset_green, cycle_done, offset_done
    global cnt, fix_plan, direction, green_plan_map, last_green_wave_send_time
    global simulation_offset_map, simulation_target_start_map
    value = copy.deepcopy(state_value or _empty_state())
    start = value["start"]
    cycle_green = value["cycle_green"]
    offset_green = value["offset_green"]
    cycle_done = value["cycle_done"]
    offset_done = value["offset_done"]
    cnt = value["cnt"]
    fix_plan = value["fix_plan"]
    direction = value["direction"]
    green_plan_map = value["green_plan_map"]
    last_green_wave_send_time = value["last_green_wave_send_time"]
    simulation_offset_map = value["simulation_offset_map"]
    simulation_target_start_map = value["simulation_target_start_map"]


def _activate_corridor_config(corridor_config):
    global _ACTIVE_CORRIDOR_ID, _ACTIVE_CORRIDOR_CONFIG
    global ORDER
    global OFFSET_STEP, GREEN_BAND_MIN_REMAIN_SECONDS
    global SIMULATION_TARGET_ELAPSED_GREEN_SECONDS, DEFAULT_CORRIDOR_CYCLE
    global DEFAULT_RED_DURATIONS, COOLDOWN_SECONDS
    global GREEN_STAGE_INDEX_MAP, BALANCE_STAGE_INDEX_MAP, PERIOD_CONFIG_MAP

    if not isinstance(corridor_config, dict):
        raise ValueError("corridor_config 必须由绿波 JSON 配置加载")
    config = copy.deepcopy(corridor_config)
    corridor_id = str(config.get("corridor_id", "")).strip()
    intersections = config.get("intersections") or []
    if not corridor_id or len(intersections) < 2:
        raise ValueError("corridor_config 缺少 corridor_id 或有效路口配置")
    ORDER = [str(item["cross_id"]) for item in intersections]
    DEFAULT_RED_DURATIONS = {
        str(item["cross_id"]): int(item.get("default_red_seconds", 0))
        for item in intersections
    }
    GREEN_STAGE_INDEX_MAP = {
        str(item["cross_id"]): int(item.get("green_stage_index", 0))
        for item in intersections
    }
    BALANCE_STAGE_INDEX_MAP = {
        str(item["cross_id"]): int(item.get("balance_stage_index", 1))
        for item in intersections
    }
    DEFAULT_CORRIDOR_CYCLE = int(config.get("cycle_seconds", 90))
    OFFSET_STEP = int(config.get("offset_step_seconds", 3))
    GREEN_BAND_MIN_REMAIN_SECONDS = int(
        config.get("minimum_remaining_green_seconds", 10)
    )
    SIMULATION_TARGET_ELAPSED_GREEN_SECONDS = int(
        config.get("simulation_target_elapsed_green_seconds", 10)
    )
    COOLDOWN_SECONDS = int(
        config.get("cooldown_seconds", max(0, DEFAULT_CORRIDOR_CYCLE - 5))
    )
    PERIOD_CONFIG_MAP = {
        str(item["period_id"]): copy.deepcopy(item)
        for item in (config.get("periods") or [])
    }
    _ACTIVE_CORRIDOR_ID = corridor_id
    _ACTIVE_CORRIDOR_CONFIG = config
    _GREEN_WAVE_CONFIG_MAP[corridor_id] = copy.deepcopy(config)
    _restore_active_state(_GREEN_WAVE_STATE_MAP.get(corridor_id))


def _reset_active_state_values():
    _restore_active_state(_empty_state())


def _period_for_time(time_str):
    try:
        current = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").time()
    except (TypeError, ValueError):
        return None
    for period in PERIOD_CONFIG_MAP.values():
        try:
            start_value = datetime.strptime(period["start_time"], "%H:%M:%S").time()
            end_value = datetime.strptime(period["end_time"], "%H:%M:%S").time()
        except (KeyError, TypeError, ValueError):
            continue
        if start_value <= current <= end_value:
            return period
    return None


def _period_settings(period_id):
    period = PERIOD_CONFIG_MAP.get(str(period_id))
    if not period:
        return None, {}
    return (
        str(period.get("reference_cross_id", "")),
        {
            str(rid): str(value)
            for rid, value in (period.get("travel_seconds") or {}).items()
        },
    )


def reset_green_wave_state(corridor_id=None):
    """清理指定走廊状态；未指定时清理全部走廊状态。"""
    global _GREEN_WAVE_STATE_MAP
    if corridor_id is None:
        _GREEN_WAVE_STATE_MAP = {}
        _reset_active_state_values()
        return
    corridor_key = str(corridor_id)
    _GREEN_WAVE_STATE_MAP.pop(corridor_key, None)
    if corridor_key == _ACTIVE_CORRIDOR_ID:
        _reset_active_state_values()


def record_green_wave_final_plan(final_action_map):
    """记录 phase_check 后各走廊实际下发方案，供下一轮继续修正。"""
    global green_plan_map, _GREEN_WAVE_STATE_MAP
    if not isinstance(final_action_map, dict):
        return
    for corridor_id, state_value in list(_GREEN_WAVE_STATE_MAP.items()):
        if not state_value.get("start"):
            continue
        config = _GREEN_WAVE_CONFIG_MAP.get(corridor_id) or {}
        order = [
            str(item["cross_id"])
            for item in (config.get("intersections") or [])
        ]
        saved_plan = copy.deepcopy(state_value.get("green_plan_map") or {})
        for item in order:
            plan = final_action_map.get(item)
            if isinstance(plan, list) and len(plan) >= 2:
                saved_plan[item] = plan[:]
        state_value["green_plan_map"] = saved_plan
        _GREEN_WAVE_STATE_MAP[corridor_id] = state_value
        if corridor_id == _ACTIVE_CORRIDOR_ID:
            green_plan_map = copy.deepcopy(saved_plan)



# --------------------------------------周期调整部分-------------------------------------
def get_cycle_step(diff: float) -> int:
    diff = abs(diff)
    return 8 if diff > 8 else int(diff)

def round_next_plan(next_plan):
    rounded_plan = {}
    for cross_id, values in next_plan.items():
        rounded_plan[cross_id] = [int(round(x)) for x in values]
    return rounded_plan

def get_red_durations_from_extend(
    extend_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]],
    order: List[str],
) -> Dict[str, int]:
    """
    从 extend_map 统计每个路口在两个放行阶段之间的 -1 阶段（黄灯/全红）红灯总时长 R_i。
    若反馈数据不足，回退到 DEFAULT_RED_DURATIONS。
    """
    red_map = {}
    if not isinstance(extend_map, dict):
        return {rid: DEFAULT_RED_DURATIONS.get(rid, 12) for rid in order}

    for rid in order:
        records = []
        for _, values in (extend_map.get(rid) or {}).items():
            if isinstance(values, list):
                records.extend(item for item in values if isinstance(item, dict))

        normalized = []
        for r in records:
            try:
                ts = int(r.get("time"))
                st = str(r.get("curStageNo", "")).strip()
                if ts > 0 and st:
                    normalized.append((ts, st))
            except (TypeError, ValueError):
                continue

        normalized.sort()
        minus_one_durations = []
        i = 0
        while i < len(normalized):
            if normalized[i][1] == "-1":
                start_ts = normalized[i][0]
                while i < len(normalized) and normalized[i][1] == "-1":
                    i += 1
                # 使用离开 -1 的切换时刻作为结束边界，而不是最后一次 -1 采样时刻。
                if i >= len(normalized):
                    continue
                end_ts = normalized[i][0]
                dur = (end_ts - start_ts) / 1000.0
                # 过滤数据中断形成的数百秒伪阶段。
                if 1 <= dur <= 30:
                    minus_one_durations.append(dur)
            else:
                i += 1

        if len(minus_one_durations) >= 2:
            median_single = statistics.median(minus_one_durations)
            red_map[rid] = int(round(median_single * 2))
        else:
            red_map[rid] = DEFAULT_RED_DURATIONS.get(rid, 12)

    return red_map

def adjust_cycle_to_corridor(
    result_action_map: Dict[str, List[int]],
    corridor_cycle: int,
    red_durations_map: Dict[str, int],
) -> Dict[str, List[int]]:
    """
    根据走廊统一完整周期 C 和每个路口的红灯总时长 R_i：
    计算各路口应下发的绿灯总时长 GreenSum_i = C - R_i。
    按现有比例步进向目标分配合理的阶段 1 和阶段 2。
    """
    new_map = copy.deepcopy(result_action_map)

    for rid, plan in result_action_map.items():
        green_index, balance_index = _stage_indices(rid)
        if not isinstance(plan, list) or len(plan) <= max(green_index, balance_index):
            continue

        r_i = red_durations_map.get(rid, DEFAULT_RED_DURATIONS.get(rid, 12))
        target_green_sum = max(20, corridor_cycle - r_i)

        cur_p1 = int(plan[green_index])
        cur_p2 = int(plan[balance_index])
        cur_green_sum = cur_p1 + cur_p2

        if cur_green_sum != target_green_sum:
            delta_sum = target_green_sum - cur_green_sum
            step_sum = get_cycle_step(delta_sum)
            if delta_sum > 0:
                new_green_sum = cur_green_sum + step_sum
            else:
                new_green_sum = cur_green_sum - step_sum
        else:
            new_green_sum = target_green_sum

        ratio = cur_p1 / cur_green_sum if cur_green_sum > 0 else 0.5
        new_p1 = max(10, int(round(new_green_sum * ratio)))
        new_p2 = max(10, new_green_sum - new_p1)

        new_map[rid][green_index] = new_p1
        new_map[rid][balance_index] = new_p2

    return new_map

def is_corridor_cycle_aligned(
    result_action_map: Dict[str, List[int]],
    corridor_cycle: int,
    red_durations_map: Dict[str, int],
    order: List[str],
) -> bool:
    """检查各路口实际下发完整的现场周期 (p1 + p2 + R_i) 是否均已达到走廊统一周期 C"""
    for rid in order:
        green_index, balance_index = _stage_indices(rid)
        if (
            rid not in result_action_map
            or len(result_action_map[rid]) <= max(green_index, balance_index)
        ):
            return False
        r_i = red_durations_map.get(rid, DEFAULT_RED_DURATIONS.get(rid, 12))
        plan = result_action_map[rid]
        total_cycle = plan[green_index] + plan[balance_index] + r_i
        if abs(total_cycle - corridor_cycle) > 1:
            return False
    return True

def adjust_cycle_one_step(
    result_action_map: Dict[str, List[int]],
    fix_rid: List[int]
) -> Dict[str, List[int]]:

    if not isinstance(fix_rid, list) or len(fix_rid) < 2:
        raise ValueError("fix_rid 必须是长度至少为2的列表")

    new_map = copy.deepcopy(result_action_map)

    ref_p1 = fix_rid[0]
    ref_p2 = fix_rid[1]

    for rid, plan in result_action_map.items():
        green_index, balance_index = _stage_indices(rid)
        if not isinstance(plan, list) or len(plan) <= max(green_index, balance_index):
            print(f"警告: 跳过异常数据 rid={rid}, plan={plan}")
            continue

        cur_p1 = plan[green_index]
        cur_p2 = plan[balance_index]

        if cur_p1 != ref_p1:
            delta_p1 = ref_p1 - cur_p1
            step_p1 = get_cycle_step(delta_p1)
            if step_p1 is None or step_p1 < 0:
                raise ValueError(f"get_cycle_step(delta_p1) 返回异常: {step_p1}")
            if delta_p1 > 0:
                cur_p1 += step_p1
            else:
                cur_p1 -= step_p1

        if cur_p2 != ref_p2:
            delta_p2 = ref_p2 - cur_p2
            step_p2 = get_cycle_step(delta_p2)
            if step_p2 is None or step_p2 < 0:
                raise ValueError(f"get_cycle_step(delta_p2) 返回异常: {step_p2}")
            if delta_p2 > 0:
                cur_p2 += step_p2
            else:
                cur_p2 -= step_p2

        new_map[rid][green_index] = max(0, cur_p1)
        new_map[rid][balance_index] = max(0, cur_p2)

    return new_map


# --------------------------------------相位差调整部分-------------------------------------

def get_two_stage_starts_from_coordinate_map(
    coordinate_map_set: Dict[str, Dict[str, int]],
    rid: str
) -> List[int]:
    try:
        if rid not in coordinate_map_set:
            return []

        data = coordinate_map_set[rid]
        starts = []

        s1 = data.get("s1")
        s2 = data.get("s2")

        if s1 is not None:
            try:
                starts.append(int(s1))
            except (ValueError, TypeError):
                pass

        if s2 is not None:
            try:
                starts.append(int(s2))
            except (ValueError, TypeError):
                pass

        return sorted(list(set(starts)))

    except Exception as e:
        print(f"get_two_stage_starts_from_coordinate_map 出错: rid={rid}, error={e}")
        return []


def get_stage_one_starts_from_extend_map(
    extend_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]],
    rid: str,
) -> List[int]:
    """从信控机 extend 数据中提取阶段 1 的实际切换时刻（毫秒）。"""
    if not isinstance(extend_map, dict):
        return []

    records = []
    for _, values in (extend_map.get(rid) or {}).items():
        if isinstance(values, list):
            records.extend(item for item in values if isinstance(item, dict))

    normalized = []
    for record in records:
        try:
            timestamp = int(record.get("time"))
            stage = str(record.get("curStageNo", "")).strip()
        except (TypeError, ValueError):
            continue
        if timestamp > 0 and stage:
            normalized.append((timestamp, stage))

    target_stage = str(_stage_indices(rid)[0] + 1)
    normalized.sort()
    starts = []
    previous_stage = None
    for timestamp, stage in normalized:
        if stage == target_stage and previous_stage != target_stage:
            starts.append(timestamp)
        previous_stage = stage
    return starts


def get_stage_one_windows_from_extend_map(
    extend_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]],
    rid: str,
) -> List[tuple[int, int]]:
    """提取已结束的阶段 1 绿灯窗口，返回毫秒级 ``(start, end)``。"""
    if not isinstance(extend_map, dict):
        return []

    records = []
    for _, values in (extend_map.get(rid) or {}).items():
        if isinstance(values, list):
            records.extend(item for item in values if isinstance(item, dict))

    normalized = []
    for record in records:
        try:
            timestamp = int(record.get("time"))
            stage = str(record.get("curStageNo", "")).strip()
        except (TypeError, ValueError):
            continue
        if timestamp > 0 and stage:
            normalized.append((timestamp, stage))

    target_stage = str(_stage_indices(rid)[0] + 1)
    normalized.sort()
    windows = []
    stage_one_start = None
    previous_stage = None
    for timestamp, stage in normalized:
        if stage == target_stage and previous_stage != target_stage:
            stage_one_start = timestamp
        elif (
            stage != target_stage
            and previous_stage == target_stage
            and stage_one_start is not None
        ):
            if timestamp > stage_one_start:
                windows.append((stage_one_start, timestamp))
            stage_one_start = None
        previous_stage = stage
    return windows


def get_observed_cycle_seconds(starts: List[int]) -> Optional[int]:
    """使用最近两个阶段 1 起点估计完整实测周期，包含 -1 红灯时间。"""
    if len(starts) < 2:
        return None
    cycle_seconds = int(round((starts[-1] - starts[-2]) / 1000.0))
    return cycle_seconds if cycle_seconds > 0 else None


def _median_int(values: List[float]) -> int:
    return int(round(statistics.median(values))) if values else 0


def _find_nearest_start(starts: List[int], target_ms: int) -> Optional[int]:
    if not starts:
        return None
    nearest = min(starts, key=lambda value: abs(value - target_ms))
    if abs(nearest - target_ms) > MAX_TIMING_MATCH_ERROR_SECONDS * 1000:
        return None
    return nearest


def _green_remaining_seconds(
    windows: List[tuple[int, int]], arrival_ms: int
) -> Optional[float]:
    for start_ms, end_ms in windows:
        if start_ms <= arrival_ms < end_ms:
            return (end_ms - arrival_ms) / 1000.0
    return None


def _normalize_timestamp_seconds(value) -> Optional[int]:
    """兼容 online 中的秒、毫秒时间戳，统一返回秒级 Unix 时间戳。"""
    try:
        timestamp = int(float(value))
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return timestamp // 1000 if timestamp >= 10_000_000_000 else timestamp


def flatten_online_data_map(
    online_data_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]],
    target_rids: Optional[set[str]] = None,
) -> List[dict]:
    """展开 Server 侧 ``rid -> 时间 -> 数据列表`` 的 online 缓存结构。"""
    if not isinstance(online_data_map, dict):
        return []

    rows = []
    for rid, time_map in online_data_map.items():
        if target_rids is not None and str(rid) not in target_rids:
            continue
        if not isinstance(time_map, dict):
            continue
        for bucket_time, values in time_map.items():
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                row = dict(value)
                row.setdefault("rid", rid)
                # 正常 online 报文有 time；缺失时才使用缓存桶时间兜底。
                row.setdefault("time", bucket_time)
                rows.append(row)
    return rows


def get_latest_online_timestamp(
    online_data_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]],
) -> Optional[int]:
    """从所有 online 记录中取得最新测试时刻，而非程序机器当前时间。"""
    latest = None
    for row in flatten_online_data_map(online_data_map):
        timestamp = _normalize_timestamp_seconds(row.get("time"))
        if timestamp is not None and (latest is None or timestamp > latest):
            latest = timestamp
    return latest


def _signed_cycle_difference(current: int, target: int, cycle: int) -> int:
    """返回 current 相对 target 的最短有符号差值。"""
    diff = (int(current) - int(target)) % cycle
    return diff - cycle if diff > cycle / 2 else diff


def calc_simulated_offset_map(
    result_action_map: Dict[str, List[int]],
    congestion_direction: str,
    simulation_timestamp: Optional[int] = None,
    order: Optional[List[str]] = None,
) -> Dict[str, object]:
    """仅依赖 online 时间和已下发方案推演绿灯窗口。

    online 报文没有 ``curStageNo``，无法判断真实信号灯处于哪个阶段；本函数因此
    只用于回放测试。它以虚拟周期起点和已下发的 P1/P2 方案推演车辆到达时是否仍
    在阶段 1 绿灯内，绝不把 online 数据误当成 extend 反馈。
    """
    global simulation_offset_map, simulation_target_start_map

    if order is None:
        order = [rid for rid in ORDER if rid in result_action_map]

    ref_rid, raw_target_offset_map = _period_settings(congestion_direction)
    if not ref_rid or not raw_target_offset_map:
        return {
            "current_offset_map": {},
            "target_offset_map": {},
            "timing_error_map": {},
            "cycle_seconds": DEFAULT_CORRIDOR_CYCLE,
            "green_band_aligned": False,
        }

    if ref_rid not in result_action_map:
        return {
            "current_offset_map": {},
            "target_offset_map": {},
            "timing_error_map": {},
            "cycle_seconds": DEFAULT_CORRIDOR_CYCLE,
            "green_band_aligned": False,
        }

    target_offset_map = {
        rid: str(int(raw_target_offset_map.get(rid, "0")))
        for rid in order
    }
    target_offset_map[ref_rid] = "0"
    current_offset_map = {}
    timing_error_map = {ref_rid: 0}
    target_start_map = {}
    arrival_report = {}
    all_passed = True

    for rid in order:
        green_index, balance_index = _stage_indices(rid)
        if (
            rid not in result_action_map
            or len(result_action_map[rid]) <= max(green_index, balance_index)
        ):
            continue

        current_offset = int(simulation_offset_map.get(rid, 0)) % DEFAULT_CORRIDOR_CYCLE
        current_offset_map[rid] = str(current_offset)
        if rid == ref_rid:
            continue

        travel_seconds = int(target_offset_map[rid])
        arrival_phase = travel_seconds % DEFAULT_CORRIDOR_CYCLE
        stage_one_seconds = max(0, int(result_action_map[rid][green_index]))
        elapsed_green = (arrival_phase - current_offset) % DEFAULT_CORRIDOR_CYCLE
        remaining_green = stage_one_seconds - elapsed_green
        window_passed = (
            elapsed_green < stage_one_seconds
            and remaining_green >= GREEN_BAND_MIN_REMAIN_SECONDS
        )

        # 首次未命中绿灯窗口时，为该路口确定一个独立的虚拟起绿目标。
        # 例如车辆第 65 秒到达、P1=44 秒时，目标起点为 55 秒：
        # 到达时已经放行 10 秒，仍剩余 34 秒绿灯；P1/P2 本身保持不变。
        desired_elapsed = min(
            SIMULATION_TARGET_ELAPSED_GREEN_SECONDS,
            max(0, stage_one_seconds - GREEN_BAND_MIN_REMAIN_SECONDS),
        )
        if not window_passed and rid not in simulation_target_start_map:
            simulation_target_start_map[rid] = (
                arrival_phase - desired_elapsed
            ) % DEFAULT_CORRIDOR_CYCLE

        active_target = simulation_target_start_map.get(rid)
        target_aligned = active_target is None or abs(
            _signed_cycle_difference(
                current_offset,
                active_target,
                DEFAULT_CORRIDOR_CYCLE,
            )
        ) <= OFFSET_TOLERANCE
        coordination_passed = window_passed and target_aligned

        if active_target is not None:
            target_start_map[rid] = str(active_target)
            timing_error_map[rid] = _signed_cycle_difference(
                current_offset,
                active_target,
                DEFAULT_CORRIDOR_CYCLE,
            )
            if coordination_passed:
                simulation_target_start_map.pop(rid, None)
        else:
            timing_error_map[rid] = 0

        all_passed = all_passed and coordination_passed
        arrival_report[rid] = {
            "source": "online_simulation",
            "travel_seconds": travel_seconds,
            "virtual_stage_one_offset_seconds": current_offset,
            "target_stage_one_offset_seconds": active_target,
            "stage_one_seconds": stage_one_seconds,
            "elapsed_green_seconds": round(elapsed_green, 1) if window_passed else None,
            "remaining_green_seconds": round(remaining_green, 1) if window_passed else None,
            "passed": window_passed,
            "target_aligned": target_aligned,
        }

    return {
        "current_offset_map": current_offset_map,
        "target_offset_map": target_offset_map,
        "target_start_map": target_start_map,
        "timing_error_map": timing_error_map,
        "cycle_seconds": DEFAULT_CORRIDOR_CYCLE,
        "green_band_aligned": all_passed,
        "arrival_report": {
            "source": "online_simulation",
            "simulation_timestamp": simulation_timestamp,
            "intersections": arrival_report,
        },
    }


def adjust_simulated_offsets_one_round(
    current_offset_map: Dict[str, Union[str, int]],
    target_start_map: Dict[str, Union[str, int]],
    cycle_seconds: int = DEFAULT_CORRIDOR_CYCLE,
):
    """每轮只移动虚拟阶段 1 起点，不修改或借用 P1/P2 阶段时长。"""
    global simulation_offset_map
    cycle = max(1, int(cycle_seconds))
    for rid, target_start in target_start_map.items():
        if rid not in current_offset_map:
            continue
        try:
            current_offset = int(current_offset_map[rid]) % cycle
            target_offset = int(target_start) % cycle
            forward = (target_offset - current_offset) % cycle
            backward = (current_offset - target_offset) % cycle
            if forward <= backward:
                delta = min(OFFSET_STEP, forward)
            else:
                delta = -min(OFFSET_STEP, backward)
            next_offset = (current_offset + delta) % cycle
            simulation_offset_map[rid] = next_offset
            print(
                f"[模拟相位调整] rid={rid}, cur={current_offset}, "
                f"target_start={target_offset}, delta={delta}, next={next_offset}, "
                "P1/P2保持不变"
            )
        except (TypeError, ValueError):
            continue


# 计算当前相位差
def calc_current_offset_map(
    coordinate_map_set: Dict[str, Dict[str, int]],
    result_action_map: Dict[str, List[int]],
    congestion_direction: str = "R",
    order: List[str] = None,
    extend_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]] = None,
) -> Dict[str, object]:
    """按最近车辆到达时刻计算下游起绿误差和绿灯窗口通过情况。"""
    try:
        if order is None:
            order = [rid for rid in ORDER if rid in result_action_map]

        # 1. 根据当前配置时段选择参考路口和累计行程时间表。
        ref_rid, raw_target_offset_map = _period_settings(congestion_direction)
        if not ref_rid or not raw_target_offset_map:
            print(f"警告: period_id={congestion_direction} 没有有效绿波配置")
            return {
                "current_offset_map": {},
                "target_offset_map": {}
            }

        if ref_rid not in result_action_map:
            print(f"警告: result_action_map 中不存在参考路口 {ref_rid}")
            return {
                "current_offset_map": {},
                "target_offset_map": {}
            }

        if len(result_action_map[ref_rid]) < 2:
            print(f"警告: 参考路口 {ref_rid} 的方案长度不足，至少需要前两位")
            return {
                "current_offset_map": {},
                "target_offset_map": {}
            }

        # 2. 绿波闭环只使用完整 extend 反馈；不能将现场绝对时间与 DQN 相对坐标混算。
        observed_starts = {
            rid: get_stage_one_starts_from_extend_map(extend_map, rid)
            for rid in order
        }
        observed_windows = {
            rid: get_stage_one_windows_from_extend_map(extend_map, rid)
            for rid in order
        }
        if not all(observed_starts.get(rid) and observed_windows.get(rid) for rid in order):
            print("警告: 绿波路口 extend 阶段反馈不完整，暂不进行相位差修正")
            return {
                "current_offset_map": {},
                "target_offset_map": {},
                "timing_error_map": {},
                "cycle_seconds": DEFAULT_CORRIDOR_CYCLE,
                "green_band_aligned": False,
            }

        # 3. 98 秒等配置值是车辆累计行程时间，禁止按现场周期取模。
        target_offset_map = {
            rid: str(int(raw_target_offset_map.get(rid, "0")))
            for rid in order
        }
        target_offset_map[ref_rid] = "0"

        # 只选择车辆已经有时间到达最远端的最近若干参考周期。
        latest_feedback_ms = max(
            starts[-1] for starts in observed_starts.values() if starts
        )
        max_travel_seconds = max(int(value) for value in target_offset_map.values())
        eligible_ref_starts = [
            value for value in observed_starts[ref_rid]
            if value + max_travel_seconds * 1000 <= latest_feedback_ms
        ][-GREEN_BAND_OBSERVATION_CYCLES:]
        if not eligible_ref_starts:
            print("警告: 尚无已完成的整条绿波车辆到达样本")
            return {
                "current_offset_map": {},
                "target_offset_map": target_offset_map,
                "timing_error_map": {},
                "cycle_seconds": DEFAULT_CORRIDOR_CYCLE,
                "green_band_aligned": False,
            }

        timing_error_map = {ref_rid: 0}
        current_offset_map = {ref_rid: "0"}
        arrival_report = {}
        all_samples_passed = True

        for rid in order:
            if rid == ref_rid:
                continue
            travel_seconds = int(target_offset_map[rid])
            errors = []
            passed_samples = 0
            remaining_values = []
            for ref_start in eligible_ref_starts:
                arrival_ms = ref_start + travel_seconds * 1000
                nearest_start = _find_nearest_start(observed_starts[rid], arrival_ms)
                if nearest_start is not None:
                    errors.append((nearest_start - arrival_ms) / 1000.0)

                remaining = _green_remaining_seconds(observed_windows[rid], arrival_ms)
                if remaining is not None:
                    remaining_values.append(remaining)
                    if remaining >= GREEN_BAND_MIN_REMAIN_SECONDS:
                        passed_samples += 1

            if not errors:
                print(f"警告: 路口 {rid} 没有可匹配的最近阶段 1 起点")
                return {
                    "current_offset_map": {},
                    "target_offset_map": target_offset_map,
                    "timing_error_map": {},
                    "cycle_seconds": DEFAULT_CORRIDOR_CYCLE,
                    "green_band_aligned": False,
                }

            timing_error = _median_int(errors)
            timing_error_map[rid] = timing_error
            current_offset_map[rid] = str(travel_seconds + timing_error)
            sample_count = len(eligible_ref_starts)
            rid_aligned = (
                sample_count >= GREEN_BAND_OBSERVATION_CYCLES
                and passed_samples == sample_count
            )
            all_samples_passed = all_samples_passed and rid_aligned
            arrival_report[rid] = {
                "travel_seconds": travel_seconds,
                "timing_error_seconds": timing_error,
                "sample_count": sample_count,
                "passed_samples": passed_samples,
                "min_remaining_green_seconds": (
                    round(min(remaining_values), 1) if remaining_values else None
                ),
            }

        return {
            "current_offset_map": current_offset_map,
            "target_offset_map": target_offset_map,
            "timing_error_map": timing_error_map,
            "cycle_seconds": DEFAULT_CORRIDOR_CYCLE,
            "green_band_aligned": all_samples_passed,
            "arrival_report": arrival_report,
        }

    except Exception as e:
        print(f"calc_current_offset_map 整体出错: {e}")
        return {
            "current_offset_map": {},
            "target_offset_map": {},
            "cycle_seconds": 0,
        }


# 做一轮相位差调整
def adjust_offset_one_round(
    result_action_map: Dict[str, List[int]],
    current_offset_map: Dict[str, Union[str, int]],
    target_offset_map: Dict[str, Union[str, int]],
    congestion_direction: str = "R",
    cycle_seconds: Optional[int] = None,
    timing_error_map: Optional[Dict[str, Union[str, int]]] = None,
) -> Dict[str, List[int]]:
    def calc_cyclic_diff(cur_offset: int, target_offset: int, cycle: int) -> int:
        forward = (target_offset - cur_offset) % cycle
        backward = (cur_offset - target_offset) % cycle
        if forward <= backward:
            return forward
        else:
            return -backward

    try:
        order = list(result_action_map.keys())

        ref_rid, _ = _period_settings(congestion_direction)
        if not ref_rid:
            print(f"警告: period_id={congestion_direction} 没有有效绿波配置")
            return copy.deepcopy(result_action_map)

        if ref_rid not in result_action_map:
            print(f"警告: result_action_map 中不存在参考路口 {ref_rid}")
            return copy.deepcopy(result_action_map)

        ref_green_index, ref_balance_index = _stage_indices(ref_rid)
        if len(result_action_map[ref_rid]) <= max(ref_green_index, ref_balance_index):
            print(f"警告: 参考路口 {ref_rid} 的方案长度不足，至少需要前两位")
            return copy.deepcopy(result_action_map)

        try:
            cycle = int(cycle_seconds or 0)
            if cycle <= 0:
                cycle = (
                    int(result_action_map[ref_rid][ref_green_index])
                    + int(result_action_map[ref_rid][ref_balance_index])
                )
        except Exception as e:
            print(f"警告: 参考路口 {ref_rid} 周期计算失败: {e}")
            return copy.deepcopy(result_action_map)

        if cycle <= 0:
            print(f"警告: 参考路口 {ref_rid} 的周期无效 cycle={cycle}")
            return copy.deepcopy(result_action_map)

        next_plan = copy.deepcopy(result_action_map)

        for rid in order:
            try:
                if rid == ref_rid:
                    continue

                green_index, balance_index = _stage_indices(rid)
                if (
                    rid not in next_plan
                    or len(next_plan[rid]) <= max(green_index, balance_index)
                ):
                    continue

                if rid not in current_offset_map or rid not in target_offset_map:
                    continue

                try:
                    cur_offset = int(current_offset_map[rid])
                    target_offset = int(target_offset_map[rid])
                    if timing_error_map and rid in timing_error_map:
                        # 正值表示下游起绿偏晚，需要缩短 P2 让下一轮 P1 提前。
                        timing_error = int(timing_error_map[rid])
                        diff = -timing_error
                    else:
                        diff = calc_cyclic_diff(cur_offset, target_offset, cycle)
                except Exception as e:
                    print(f"警告: 路口 {rid} 相位差解析失败: {e}")
                    continue

                if diff > 0:
                    delta = min(int(OFFSET_STEP), diff)
                elif diff < 0:
                    delta = -min(int(OFFSET_STEP), abs(diff))
                else:
                    delta = 0

                old_p1 = int(next_plan[rid][green_index])
                old_p2 = int(next_plan[rid][balance_index])
                green_sum = old_p1 + old_p2

                new_p2 = max(10, old_p2 + delta)
                new_p1 = max(10, green_sum - new_p2)

                next_plan[rid][green_index] = new_p1
                next_plan[rid][balance_index] = new_p2

                print(
                    f"[offset调整] rid={rid}, cur={cur_offset}, target={target_offset}, "
                    f"diff={diff}, delta={delta}, P1: {old_p1}->{new_p1}, P2: {old_p2}->{new_p2}"
                )

            except Exception as e:
                print(f"adjust_offset_one_round 处理路口 {rid} 出错: {e}")
                continue

        return next_plan

    except Exception as e:
        print(f"adjust_offset_one_round 整体出错: {e}")
        return copy.deepcopy(result_action_map)


def offsets_aligned(
    current_offset_map: Dict[str, Union[str, int]],
    target_offset_map: Dict[str, Union[str, int]],
    cycle_seconds: int,
    tolerance: int = OFFSET_TOLERANCE,
) -> bool:
    """允许采样误差，判断实际相位差是否已达到目标。"""
    if not current_offset_map or not target_offset_map or cycle_seconds <= 0:
        return False

    for rid, target in target_offset_map.items():
        if rid not in current_offset_map:
            return False
        try:
            current_value = int(current_offset_map[rid])
            target_value = int(target)
        except (TypeError, ValueError):
            return False
        diff = abs((current_value - target_value) % cycle_seconds)
        if min(diff, cycle_seconds - diff) > tolerance:
            return False
    return True


def _apply_green_wave_coordination_active(
    time_str: str,
    cur_action_map: Dict[str, List[int]],
    result_action_map: Dict[str, List[int]],
    coordinate_map_set: Dict[str, Dict[str, int]],
    extend_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]] = None,
    simulation_mode: bool = False,
    simulation_timestamp: Optional[int] = None,
    report_out: Optional[Dict[str, object]] = None,
) -> Dict[str, List[int]]:
    """
    绿波走廊协同控制独立主入口函数：
    处理高峰期检测、状态机维护、走廊周期统一对齐(扣除红灯)、相位差微调及下发冷却保护。
    """
    global start, cycle_green, offset_green, cycle_done, offset_done
    global cnt, fix_plan, direction, green_plan_map, last_green_wave_send_time

    active_period = _period_for_time(time_str)

    report = {
        "status": "success",
        "corridor_id": _ACTIVE_CORRIDOR_ID,
        "mode": "online_simulation" if simulation_mode else "extend_feedback",
        "test_time": time_str,
        "peak": active_period["period_id"] if active_period else "none",
        "cycle_aligned": False,
        "green_band_aligned": False,
        "final_aligned": False,
        "target_offset_map": {},
        "target_start_map": {},
        "current_offset_map": {},
        "arrival_report": {},
        "message": "",
    }

    def publish_report():
        report["final_aligned"] = bool(
            report.get("cycle_aligned") and report.get("green_band_aligned")
        )
        if isinstance(report_out, dict):
            report_out.clear()
            report_out.update(copy.deepcopy(report))

    if active_period:
        alarm_green = True
        alarm_direction = str(active_period["period_id"])
        print(f"当前处于绿波时段: {alarm_direction}")
    else:
        alarm_green = False
        alarm_direction = ""
        print("当前未开启绿波")

    # 非绿波时段立即退出，防止旧绿波方案跨时段继续下发。
    if not alarm_green:
        if start:
            print("绿波时段结束，重置绿波状态。")
            _reset_active_state_values()
        report["message"] = "当前不在绿波启用时段"
        publish_report()
        return result_action_map

    # online 回放按报文时间推进冷却周期；实车保持机器当前时间。
    current_time_sec = (
        int(simulation_timestamp)
        if simulation_mode and simulation_timestamp is not None
        else time.time()
    )
    if not start:
        start = True
        cycle_green = True
        offset_green = False
        direction = alarm_direction
        cnt = 0
        last_green_wave_send_time = 0
        green_plan_map = {item: cur_action_map[item][:] for item in ORDER if item in cur_action_map}

    if start and ORDER and all(item in green_plan_map for item in ORDER):
        working_plan = {
            item: green_plan_map.get(item, cur_action_map[item])[:]
            for item in ORDER
            if item in cur_action_map
        }

        # 检查下发保护冷却时间，防止重发频率高于走廊统一周期 C
        cooldown_passed = (last_green_wave_send_time == 0) or (
            current_time_sec - last_green_wave_send_time >= COOLDOWN_SECONDS
        )

        if not cooldown_passed:
            print(f"绿波冷却中（距离上次调整不足 {COOLDOWN_SECONDS} 秒），保持当前已下发周期方案。")
            report["cycle_aligned"] = bool(cycle_done)
            report["green_band_aligned"] = bool(offset_done)
            report["message"] = "绿波冷却中，保持当前已下发方案"
            for item in ORDER:
                if item in result_action_map and item in working_plan:
                    result_action_map[item] = working_plan[item][:]
        else:
            # online 不包含阶段号，回放测试只能使用配置的红灯时长推演周期；
            # 实车仍优先从 extend 反馈统计 R_i。
            if simulation_mode:
                red_durations = {
                    rid: DEFAULT_RED_DURATIONS.get(rid, 12)
                    for rid in ORDER
                }
                print("绿波模拟模式：使用 online 时间和当前方案推演绿灯窗口。")
            else:
                red_durations = get_red_durations_from_extend(extend_map, ORDER)

            # ----------------------------------- 周期调整部分 ---------------------------
            if cycle_green:
                cnt += 1
                next_plan = round_next_plan(
                    adjust_cycle_to_corridor(
                        working_plan,
                        DEFAULT_CORRIDOR_CYCLE,
                        red_durations
                    )
                )
                green_plan_map = next_plan
                for item in ORDER:
                    if item in result_action_map and item in next_plan:
                        result_action_map[item] = next_plan[item][:]

                cycle_done = is_corridor_cycle_aligned(
                    next_plan,
                    DEFAULT_CORRIDOR_CYCLE,
                    red_durations,
                    ORDER
                )
                print(f"走廊统一周期 C={DEFAULT_CORRIDOR_CYCLE} 秒对齐状态: cycle_done = {cycle_done}")
                report["cycle_aligned"] = bool(cycle_done)
                report["message"] = (
                    "走廊周期已对齐，下一轮开始检查绿灯窗口"
                    if cycle_done
                    else "正在调整走廊统一周期"
                )
                if cycle_done:
                    cycle_green = False
                    offset_green = True
                last_green_wave_send_time = current_time_sec

            # ------------------------------------ 相位差调整部分 -----------------------------------------------
            elif offset_green:
                if simulation_mode:
                    res = calc_simulated_offset_map(
                        result_action_map=working_plan,
                        congestion_direction=direction,
                        simulation_timestamp=simulation_timestamp,
                    )
                else:
                    res = calc_current_offset_map(
                        coordinate_map_set=coordinate_map_set,
                        result_action_map=working_plan,
                        congestion_direction=direction,
                        extend_map=extend_map,
                    )
                current_offset_map = res.get("current_offset_map", {})
                target_offset_map = res.get("target_offset_map", {})
                target_start_map = res.get("target_start_map", {})
                timing_error_map = res.get("timing_error_map", {})
                cycle_seconds = int(res.get("cycle_seconds", 0) or DEFAULT_CORRIDOR_CYCLE)
                green_band_aligned = bool(res.get("green_band_aligned", False))

                report["cycle_aligned"] = is_corridor_cycle_aligned(
                    working_plan,
                    DEFAULT_CORRIDOR_CYCLE,
                    red_durations,
                    ORDER,
                )
                report["green_band_aligned"] = green_band_aligned
                report["target_offset_map"] = copy.deepcopy(target_offset_map)
                report["target_start_map"] = copy.deepcopy(target_start_map)
                report["current_offset_map"] = copy.deepcopy(current_offset_map)
                report["arrival_report"] = copy.deepcopy(
                    res.get("arrival_report", {})
                )

                print("目标累计行程时间：", target_offset_map)
                if simulation_mode and target_start_map:
                    print("模拟目标阶段 1 起绿位置：", target_start_map)
                offset_source = "模拟阶段 1 起绿相位：" if simulation_mode else "实测阶段 1 起绿时间："
                print(offset_source, current_offset_map)
                print("车辆到达绿灯窗口报告：", res.get("arrival_report", {}))

                if not current_offset_map or not target_offset_map or cycle_seconds <= 0:
                    if simulation_mode:
                        print("绿波模拟数据不完整，保持当前已下发周期方案。")
                        report["message"] = "绿波模拟数据不完整"
                    else:
                        print("绿波相位差等待完整 extend 阶段反馈。")
                        report["message"] = "等待完整 extend 阶段反馈"
                    for item in ORDER:
                        if item in result_action_map and item in working_plan:
                            result_action_map[item] = working_plan[item][:]
                elif green_band_aligned:
                    print("最近车辆到达样本均处于绿灯且余量达标，保持绿波协同运行。")
                    offset_done = True
                    report["message"] = "车辆到达绿灯窗口已达标"
                    for item in ORDER:
                        if item in result_action_map and item in working_plan:
                            result_action_map[item] = working_plan[item][:]
                else:
                    offset_done = False
                    if simulation_mode:
                        report["message"] = "车辆到达绿灯窗口未达标，正在独立调整模拟起绿位置"
                        adjust_simulated_offsets_one_round(
                            current_offset_map=current_offset_map,
                            target_start_map=target_start_map,
                            cycle_seconds=cycle_seconds,
                        )
                        # online 回放只移动虚拟相位，周期对齐后的阶段时长保持不变。
                        next_plan = copy.deepcopy(working_plan)
                    else:
                        report["message"] = "车辆到达绿灯窗口未达标，已生成下一轮方案"
                        next_plan = adjust_offset_one_round(
                            result_action_map=working_plan,
                            current_offset_map=current_offset_map,
                            target_offset_map=target_offset_map,
                            congestion_direction=direction,
                            cycle_seconds=cycle_seconds,
                            timing_error_map=timing_error_map,
                        )
                    green_plan_map = round_next_plan(next_plan)
                    for item in ORDER:
                        if item in result_action_map and item in green_plan_map:
                            result_action_map[item] = green_plan_map[item][:]
                    last_green_wave_send_time = current_time_sec

    publish_report()
    return result_action_map


def apply_green_wave_coordination(
    time_str: str,
    cur_action_map: Dict[str, List[int]],
    result_action_map: Dict[str, List[int]],
    coordinate_map_set: Dict[str, Dict[str, int]],
    extend_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]] = None,
    simulation_mode: bool = False,
    simulation_timestamp: Optional[int] = None,
    report_out: Optional[Dict[str, object]] = None,
    corridor_config: Optional[Dict[str, object]] = None,
) -> Dict[str, List[int]]:
    """按走廊配置加载独立状态并执行一轮协调。"""
    if not isinstance(corridor_config, dict):
        raise ValueError("必须通过 green_wave_corridors.json 提供 corridor_config")
    corridor = copy.deepcopy(corridor_config)
    _activate_corridor_config(corridor)
    corridor_id = _ACTIVE_CORRIDOR_ID
    try:
        return _apply_green_wave_coordination_active(
            time_str=time_str,
            cur_action_map=cur_action_map,
            result_action_map=result_action_map,
            coordinate_map_set=coordinate_map_set,
            extend_map=extend_map,
            simulation_mode=simulation_mode,
            simulation_timestamp=simulation_timestamp,
            report_out=report_out,
        )
    finally:
        _GREEN_WAVE_STATE_MAP[corridor_id] = _capture_active_state()



# --------------------------------------拥塞系数判断部分-------------------------------------
# 窗口
WINDOW_SEC = 5 * 60
# 方向映射
DIR_ALIAS = {
    "L": "L", "L1": "L", "L2": "L", "L3": "L",
    "R": "R", "R1": "R", "R2": "R", "R3": "R",
    "U": "U", "U1": "U", "U2": "U", "U3": "U",
    "D": "D", "D1": "D", "D2": "D", "D3": "D",
}
VALID_CANON_DIRS = {"L", "R", "U", "D"}

# 判断当前时间
def get_latest_normal_time(online_data):
    latest_time = None

    try:
        for item in online_data:
            if not isinstance(item, dict):
                continue

            if "time" not in item:
                continue

            try:
                timestamp = int(item["time"])
            except (ValueError, TypeError):
                # time 字段异常，直接跳过
                continue

            if latest_time is None or timestamp > latest_time:
                latest_time = timestamp

        if latest_time is None:
            return None

        try:
            return datetime.fromtimestamp(latest_time).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    except Exception as e:
        print(f"[警告] get_latest_normal_time 执行失败: {e}")
        return None

# 判断是否位于早高峰
def is_in_morning_peak_str(time_str):

    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

        start = dt.replace(hour=7, minute=30, second=0)
        end = dt.replace(hour=9, minute=0, second=0)

        return start <= dt <= end

    except Exception as e:
        print(f"[警告] is_in_morning_peak_str 执行失败: {e}")
        return False


# 判断是否位于晚高峰
def is_in_evening_peak_str(time_str):
    """
    判断字符串时间是否在晚高峰之间
    格式: 'YYYY-MM-DD HH:MM:SS'
    """
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

        start = dt.replace(hour=17, minute=00, second=0)
        end = dt.replace(hour=19, minute=0, second=0)

        return start <= dt <= end

    except Exception as e:
        print(f"[警告] is_in_evening_peak_str 执行失败: {e}")
        return False

# 把输入安全的转成整数
def safe_int(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return int(x)
    try:
        return int(str(x).strip())
    except Exception:
        return None

# 统一一下方向
def normalize_dir(d):
    if d is None:
        return None
    d = str(d).strip().upper()
    if not d:
        return None
    return DIR_ALIAS.get(d)

# 统一处理“一个路口”或“多个路口”的情况
def iter_junction_ids(v):
    if v is None:
        return
    if isinstance(v, list):
        for x in v:
            s = str(x).strip()
            if s:
                yield s
    else:
        s = str(v).strip()
        if s:
            yield s

# 选择最近最大拥塞系数
def better_max(cur_level, cur_time, new_level, new_time):
    if cur_level is None:
        return new_level, new_time
    if new_level > cur_level:
        return new_level, new_time
    if new_level == cur_level:
        if cur_time is None or (new_time is not None and new_time > cur_time):
            return new_level, new_time
    return cur_level, cur_time

#计算拥塞等级
def calc_ci_level(data):
    x1 = 0.15
    x2 = 1.008

    speed = data.get("speed", 0)
    max_speed = data.get("max_speed", 1)
    nostop_speed = data.get("nostop_speed", 0)
    jam_state_no = data.get("jam_state_no", 0)

    try:
        speed = float(speed) if speed is not None else 0
        nostop_speed = float(nostop_speed) if nostop_speed is not None else 0
        max_speed = float(max_speed)
    except Exception:
        return None

    if max_speed <= 0:
        return None

    c1 = 1 - speed / max_speed
    c2 = 1 - nostop_speed / max_speed
    ci = x1 * c1 + x2 * c2

    if ci < 0.2:
        level = 0
    elif ci < 0.4:
        level = 1
    elif ci < 0.6:
        level = 2
    elif ci < 0.8:
        level = 3
    else:
        level = 4

    if jam_state_no in (1, 2):
        level = max(level, 3)

    return level

# 构建路口拓扑链条
def build_ordered_chain_from_topology(topology):
    if not topology:
        return []

    start = None
    for jid, nbrs in topology.items():
        left_jid = str(nbrs.get("L", "")).strip()
        if not left_jid:
            start = jid
            break

    if start is None:
        start = next(iter(topology))

    chain = []
    visited = set()
    cur = start

    while cur and cur not in visited:
        chain.append(cur)
        visited.add(cur)

        next_jid = str(topology.get(cur, {}).get("R", "")).strip()
        cur = next_jid if next_jid else None

    for jid in topology:
        if jid not in visited:
            chain.append(jid)

    return chain

# 报警函数（暂时不使用）
def check_lr_alarm(final_result, chain, time_ref):
    if not chain:
        print(f"[提示] 时间 {time_ref}：未构造出有效的 L/R 路口链，跳过连续报警判断。")
        return False, ""

    alarm_triggered = False
    alarm_direction = ""

    # R 方向
    r_seq = []
    for jid in chain:
        level = final_result.get(jid, {}).get("R")

        if level == 4:
            print(f"[报警] 时间 {time_ref}：路口 {jid} 的 R 方向拥塞等级达到 4")
            alarm_triggered = True
            alarm_direction = "R"
            return alarm_triggered, alarm_direction

        if level == 2:
            r_seq.append(jid)
            if len(r_seq) >= 2:
                print(f"[报警] 时间 {time_ref}：R 方向连续 3 个路口拥塞等级为 3，路口序列：{r_seq[-3:]}")
                alarm_triggered = True
                alarm_direction = "R"
                return alarm_triggered, alarm_direction
        else:
            r_seq = []

    # L 方向
    l_seq = []
    for jid in reversed(chain):
        level = final_result.get(jid, {}).get("L")

        if level == 4:
            print(f"[报警] 时间 {time_ref}：路口 {jid} 的 L 方向拥塞等级达到 4")
            alarm_triggered = True
            alarm_direction = "L"
            break

        if level == 2:
            l_seq.append(jid)
            if len(l_seq) >= 2:
                print(f"[报警] 时间 {time_ref}：L 方向连续 3 个路口拥塞等级为 3，路口序列：{l_seq[-3:]}")
                alarm_triggered = True
                alarm_direction = "L"
                break
        else:
            l_seq = []

    return alarm_triggered, alarm_direction

# 找到最近5分钟的窗口起点
def get_latest_time_and_window(online_data):
    try:
        times = []
        for row in online_data:
            try:
                if not isinstance(row, dict):
                    continue
                t = safe_int(row.get("time"))
                if t is not None:
                    times.append(t)
            except Exception:
                continue

        if not times:
            print("get_latest_time_and_window 警告: online_data 中未找到可用的 time 字段。")
            return None, None

        time_ref = max(times)
        window_start = time_ref - WINDOW_SEC
        return time_ref, window_start

    except Exception as e:
        print(f"get_latest_time_and_window 出错: {e}")
        return None, None

# 对于每条道路，保留最近5分钟内拥塞等级最大值
def get_rid_best_levels(online_data, window_start, time_ref):
    rid_best = defaultdict(lambda: (None, None))

    for row in online_data:
        if not isinstance(row, dict):
            continue

        rid = row.get("rid")
        if not rid:
            continue
        rid = str(rid).strip()

        t = safe_int(row.get("time"))
        if t is None:
            continue
        if t < window_start or t > time_ref:
            continue

        level = calc_ci_level(row)
        if level is None:
            continue

        cur_level, cur_time = rid_best[rid]
        rid_best[rid] = better_max(cur_level, cur_time, level, t)

    return rid_best

# 从路段映射到路口上
def aggregate_to_junction_dirs(rid_best, road_junction):
    junction_dir_best = defaultdict(
        lambda: {
            "L": None,
            "R": None,
            "U": None,
            "D": None,
        }
    )

    for rid, (level, t_of_max) in rid_best.items():
        if level is None:
            continue

        dir_map = road_junction.get(rid)
        if not isinstance(dir_map, dict):
            continue

        for raw_dir, jval in dir_map.items():
            canon_dir = normalize_dir(raw_dir)
            if canon_dir not in VALID_CANON_DIRS:
                continue

            for jid in iter_junction_ids(jval):
                cur_level = junction_dir_best[jid][canon_dir]
                if cur_level is None or level > cur_level:
                    junction_dir_best[jid][canon_dir] = level

    return junction_dir_best

# 生成初步结果
def build_final_result(junction_dir_best, topology, time_ref):
    final_result = {}

    for jid, dirs in junction_dir_best.items():
        final_result[jid] = {
            "time": time_ref,
            "L": dirs["L"],
            "R": dirs["R"],
            "U": dirs["U"],
            "D": dirs["D"],
        }

    for jid in topology:
        if jid not in final_result:
            final_result[jid] = {
                "time": time_ref,
                "L": None,
                "R": None,
                "U": None,
                "D": None,
            }

    return final_result

# 区域扩散以及拥塞传播
# 把等级转成 0~4 或 None
def _safe_level(x):
    if x is None:
        return None
    try:
        x = int(x)
    except Exception:
        return None
    return max(0, min(4, x))

# 给 final_result 补 pressure 字段，pressure 设计为按方向累计，当前链式传播只使用 L/R
def _init_pressure_field(final_result):
    for jid, info in final_result.items():
        if "pressure" not in info or not isinstance(info["pressure"], dict):
            info["pressure"] = {"L": 0.0, "R": 0.0}
        else:
            info["pressure"].setdefault("L", 0.0)
            info["pressure"].setdefault("R", 0.0)

# 压力衰减：若没有明显新增压力，则衰减。
def _decay_pressure(p, decay_factor=0.5, clear_epsilon=0.1):
    p = p * decay_factor
    if p < clear_epsilon:
        p = 0.0
    return p

# 在单个方向上进行一次传播
def _propagate_one_direction(
    result,
    chain,
    direction,
    threshold=3.0,
    pressure_gain=1.0,
    force_diff=2,
    decay_factor=0.5,
    clear_epsilon=0.1,
):
    try:
        if not result or not chain:
            return

        if direction == "R":
            pairs = [(chain[i], chain[i + 1]) for i in range(len(chain) - 1)]
        elif direction == "L":
            pairs = [(chain[i], chain[i - 1]) for i in range(len(chain) - 1, 0, -1)]
        else:
            return

        if threshold is None or threshold <= 0:
            print(f"_propagate_one_direction 警告: threshold={threshold} 非法，跳过传播。")
            return

        got_pressure = {(jid, direction): 0.0 for jid in chain}

        for src, dst in pairs:
            try:
                src_level = _safe_level(result.get(src, {}).get(direction))
                dst_level = _safe_level(result.get(dst, {}).get(direction))

                if src_level is None or dst_level is None:
                    continue

                if src_level <= dst_level:
                    continue

                if dst not in result or not isinstance(result[dst], dict):
                    continue

                if "pressure" not in result[dst] or not isinstance(result[dst]["pressure"], dict):
                    result[dst]["pressure"] = {"L": 0.0, "R": 0.0}
                result[dst]["pressure"].setdefault("L", 0.0)
                result[dst]["pressure"].setdefault("R", 0.0)

                diff = src_level - dst_level

                if diff >= force_diff and dst_level < 4:
                    dst_level += 1
                    result[dst][direction] = dst_level

                delta_pressure = pressure_gain * diff
                result[dst]["pressure"][direction] += delta_pressure
                got_pressure[(dst, direction)] += delta_pressure

                while (
                    result[dst]["pressure"][direction] >= threshold
                    and result[dst].get(direction) is not None
                    and result[dst][direction] < 4
                ):
                    result[dst][direction] += 1
                    result[dst]["pressure"][direction] -= threshold

            except Exception as e:
                print(f"_propagate_one_direction 处理边 {src}->{dst} 出错: {e}")
                continue

        for jid in chain:
            try:
                if jid not in result or not isinstance(result[jid], dict):
                    continue

                if "pressure" not in result[jid] or not isinstance(result[jid]["pressure"], dict):
                    result[jid]["pressure"] = {"L": 0.0, "R": 0.0}
                result[jid]["pressure"].setdefault("L", 0.0)
                result[jid]["pressure"].setdefault("R", 0.0)

                if got_pressure[(jid, direction)] < clear_epsilon:
                    result[jid]["pressure"][direction] = _decay_pressure(
                        result[jid]["pressure"][direction],
                        decay_factor=decay_factor,
                        clear_epsilon=clear_epsilon,
                    )
            except Exception as e:
                print(f"_propagate_one_direction 衰减 jid={jid} 出错: {e}")
                continue

    except Exception as e:
        print(f"_propagate_one_direction 整体出错: {e}")

# 区域协同传播函数
def propagate_chain_congestion(
    final_result,
    chain,
    threshold=3.0,
    pressure_gain=1.0,
    force_diff=2,
    decay_factor=0.5,
    clear_epsilon=0.1,
):
    try:
        new_result = deepcopy(final_result) if final_result is not None else {}
        _init_pressure_field(new_result)

        if new_result:
            try:
                first_val = next(iter(new_result.values()))
                any_time = first_val.get("time") if isinstance(first_val, dict) else None
            except Exception:
                any_time = None
        else:
            any_time = None

        if chain is None:
            chain = []

        for jid in chain:
            if jid not in new_result:
                new_result[jid] = {
                    "time": any_time,
                    "L": None,
                    "R": None,
                    "U": None,
                    "D": None,
                    "pressure": {"L": 0.0, "R": 0.0},
                }

        _propagate_one_direction(
            new_result,
            chain,
            direction="R",
            threshold=threshold,
            pressure_gain=pressure_gain,
            force_diff=force_diff,
            decay_factor=decay_factor,
            clear_epsilon=clear_epsilon,
        )

        _propagate_one_direction(
            new_result,
            chain,
            direction="L",
            threshold=threshold,
            pressure_gain=pressure_gain,
            force_diff=force_diff,
            decay_factor=decay_factor,
            clear_epsilon=clear_epsilon,
        )

        return new_result

    except Exception as e:
        print(f"propagate_chain_congestion 出错: {e}")
        return deepcopy(final_result) if final_result is not None else {}
