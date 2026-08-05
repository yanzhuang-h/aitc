from collections import defaultdict
from copy import deepcopy
import copy
from typing import Dict, List, Optional, Union
from datetime import datetime
import time

# --------------------------------------相位差调整配置-------------------------------------
REF_RID = "1300370"
RIGHT_OFFSET_RID = "1300248"
LEFT_OFFSET_RID = "2705050"
LEFT_TARGET_OFFSET_MAP = {
    "2705050": "0",
    "1300370": "26",
    "1300373": "65",
    "1300248": "98",
}
RIGHT_TARGET_OFFSET_MAP = {
    "2705050": "98",
    "1300370": "72",
    "1300373": "33",
    "1300248": "0",
}
OFFSET_STEP = 8
OFFSET_TOLERANCE = 1
DEFAULT_CORRIDOR_CYCLE = 90
DEFAULT_RED_DURATIONS = {
    "2705050": 15,
    "1300370": 14,
    "1300373": 0,
    "1300248": 16,
}
PHASE_CHECK_BOUNDS = {
    "2705050": {"p1": (30, 61), "p2": (25, 58)},
    "1300370": {"p1": (35, 60), "p2": (30, 50)},
    "1300373": {"p1": (24, 58), "p2": (24, 58)},
    "1300248": {"p1": (15, 58), "p2": (30, 60)},
}
GREEN_WAVE_STAGE_INDEX = {
    "2705050": 0,  # P1 是 LR 东西绿波干线
    "1300370": 0,  # P1 是 LR 东西绿波干线
    "1300373": 1,  # P2 是 LR 东西绿波干线
    "1300248": 1,  # P2 是 LR 东西绿波干线
}

# --------------------------------------绿波控制全局状态-------------------------------------
ORDER = ["2705050", "1300370", "1300373", "1300248"]
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


def reset_green_wave_state():
    """清理一轮绿波协调状态，避免非高峰继续沿用旧方案。"""
    global start, cycle_green, offset_green, cycle_done, offset_done
    global cnt, fix_plan, direction, green_plan_map, last_green_wave_send_time
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


def record_green_wave_final_plan(final_action_map):
    """记录 phase_check 后实际下发的绿波方案，供下一轮继续修正。"""
    global green_plan_map
    if not start or not isinstance(final_action_map, dict):
        return
    for item in ORDER:
        plan = final_action_map.get(item)
        if isinstance(plan, list) and len(plan) >= 2:
            green_plan_map[item] = plan[:]



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
                end_ts = normalized[i - 1][0]
                dur = (end_ts - start_ts) / 1000.0
                if dur > 0:
                    minus_one_durations.append(dur)
            else:
                i += 1

        if len(minus_one_durations) >= 2:
            avg_single = sum(minus_one_durations) / len(minus_one_durations)
            red_map[rid] = int(round(avg_single * 2))
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
        if not isinstance(plan, list) or len(plan) < 2:
            continue

        r_i = red_durations_map.get(rid, DEFAULT_RED_DURATIONS.get(rid, 12))
        target_green_sum = max(20, corridor_cycle - r_i)

        bounds = PHASE_CHECK_BOUNDS.get(rid, {"p1": (10, 80), "p2": (10, 80)})
        p1_min, p1_max = bounds["p1"]
        p2_min, p2_max = bounds["p2"]

        cur_p1 = int(plan[0])
        cur_p2 = int(plan[1])
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
        proposed_p1 = int(round(new_green_sum * ratio))

        valid_p1_min = max(p1_min, new_green_sum - p2_max)
        valid_p1_max = min(p1_max, new_green_sum - p2_min)

        new_p1 = max(valid_p1_min, min(valid_p1_max, proposed_p1))
        new_p2 = new_green_sum - new_p1

        new_map[rid][0] = new_p1
        new_map[rid][1] = new_p2

    return new_map

def is_corridor_cycle_aligned(
    result_action_map: Dict[str, List[int]],
    corridor_cycle: int,
    red_durations_map: Dict[str, int],
    order: List[str],
) -> bool:
    """检查各路口实际下发完整的现场周期 (p1 + p2 + R_i) 是否均已达到走廊统一周期 C"""
    for rid in order:
        if rid not in result_action_map or len(result_action_map[rid]) < 2:
            return False
        r_i = red_durations_map.get(rid, DEFAULT_RED_DURATIONS.get(rid, 12))
        plan = result_action_map[rid]
        total_cycle = plan[0] + plan[1] + r_i
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
        if not isinstance(plan, list) or len(plan) < 2:
            print(f"警告: 跳过异常数据 rid={rid}, plan={plan}")
            continue

        cur_p1 = plan[0]
        cur_p2 = plan[1]

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

        new_map[rid][0] = max(0, cur_p1)
        new_map[rid][1] = max(0, cur_p2)

    return new_map


# --------------------------------------相位差调整部分-------------------------------------

def get_two_stage_starts_from_coordinate_map(
    coordinate_map_set: Dict[str, Dict[str, int]],
    rid: str,
    result_action_map: Optional[Dict[str, List[int]]] = None,
) -> List[int]:
    try:
        if isinstance(coordinate_map_set, dict) and rid in coordinate_map_set:
            data = coordinate_map_set[rid]
            if isinstance(data, dict):
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

                if starts:
                    return sorted(list(set(starts)))

        # 回退：从 result_action_map 提取相对阶段起点 [0, stage1_len]
        if isinstance(result_action_map, dict) and rid in result_action_map:
            plan = result_action_map[rid]
            if isinstance(plan, list) and len(plan) >= 2:
                return [0, int(plan[0])]

        return []

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

    normalized.sort()
    starts = []
    previous_stage = None
    for timestamp, stage in normalized:
        if stage == "1" and previous_stage != "1":
            starts.append(timestamp)
        previous_stage = stage
    return starts


def get_observed_cycle_seconds(starts: List[int]) -> Optional[int]:
    """使用最近两个阶段 1 起点估计完整实测周期，包含 -1 红灯时间。"""
    if len(starts) < 2:
        return None
    cycle_seconds = int(round((starts[-1] - starts[-2]) / 1000.0))
    return cycle_seconds if cycle_seconds > 0 else None


def compute_green_wave_target_offsets(
    coordinate_map_set: Dict[str, Dict[str, int]],
    result_action_map: Dict[str, List[int]],
    congestion_direction: str = "R",
    order: List[str] = None,
    extend_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]] = None,
) -> Dict[str, Dict[str, str]]:
    def cyclic_distance(a: int, b: int, cycle: int) -> int:
        diff = abs(a - b)
        return min(diff, cycle - diff)

    try:
        if order is None:
            order = list(result_action_map.keys())

        # 1. 根据方向选择参考路口和目标相位差表
        if congestion_direction == "R":
            ref_rid = RIGHT_OFFSET_RID
            raw_target_offset_map = RIGHT_TARGET_OFFSET_MAP
        elif congestion_direction == "L":
            ref_rid = LEFT_OFFSET_RID
            raw_target_offset_map = LEFT_TARGET_OFFSET_MAP
        else:
            print(f"警告: congestion_direction={congestion_direction} 无效，应为 'R' 或 'L'")
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

        # 2. 优先使用信控机阶段 1 实测起点计算完整周期（含 -1 红灯）。
        observed_starts = {
            rid: get_stage_one_starts_from_extend_map(extend_map, rid)
            for rid in order
        }
        has_complete_extend_feedback = all(len(observed_starts.get(rid, [])) >= 2 for rid in order)
        observed_cycle = get_observed_cycle_seconds(observed_starts.get(ref_rid, [])) if has_complete_extend_feedback else None

        # 若现场数据不足，回退到下发方案前两个阶段之和，保证兼容旧链路。
        try:
            cycle = observed_cycle or DEFAULT_CORRIDOR_CYCLE
        except Exception as e:
            print(f"警告: 参考路口 {ref_rid} 周期计算失败: {e}")
            return {
                "current_offset_map": {},
                "target_offset_map": {}
            }

        if cycle <= 0:
            print(f"警告: 参考路口 {ref_rid} 的周期无效 cycle={cycle}")
            return {
                "current_offset_map": {},
                "target_offset_map": {},
                "cycle_seconds": 0,
            }

        # 3. 参考路口与各路口相位起点：在 extend 反馈完整时优先使用 extend，否则使用 coordinate_map 或方案回退
        starts_map = {}
        if has_complete_extend_feedback:
            starts_map = observed_starts
        else:
            for rid in order:
                starts_map[rid] = get_two_stage_starts_from_coordinate_map(
                    coordinate_map_set, rid, result_action_map
                )

        ref_starts = starts_map.get(ref_rid)
        if not ref_starts:
            print(f"警告: 参考路口 {ref_rid} 没有有效协调相位数据")
            return {
                "current_offset_map": {},
                "target_offset_map": {}
            }

        # 4. 处理目标相位差：超出周期的取模，确保 ref_rid 为 0
        target_offset_map = {}
        for rid in order:
            try:
                raw_target = int(raw_target_offset_map.get(rid, "0"))
                target_offset_map[rid] = str(raw_target % cycle)
            except Exception:
                target_offset_map[rid] = "0"

        target_offset_map[ref_rid] = "0"

        # 5. 计算当前相位差
        current_offset_map = {}

        for rid in order:
            try:
                if rid == ref_rid:
                    current_offset_map[rid] = "0"
                    continue

                node_starts = starts_map.get(rid) or []

                gw_idx = GREEN_WAVE_STAGE_INDEX.get(rid, 0)
                ref_gw_idx = GREEN_WAVE_STAGE_INDEX.get(ref_rid, 0)

                try:
                    target_rel = int(target_offset_map.get(rid, "0"))
                except Exception:
                    target_rel = 0

                if len(node_starts) > gw_idx and len(ref_starts) > ref_gw_idx:
                    tn = node_starts[gw_idx]
                    tr = ref_starts[ref_gw_idx]
                    best_offset = (int(tn) - int(tr)) % cycle
                else:
                    candidates = []
                    for tn in node_starts:
                        for tr in ref_starts:
                            try:
                                diff = (int(tn) - int(tr)) % cycle
                                candidates.append(int(diff))
                            except Exception:
                                continue

                    if not candidates:
                        current_offset_map[rid] = "0"
                        continue

                    best_offset = min(
                        candidates,
                        key=lambda x: cyclic_distance(x, target_rel, cycle)
                    )
                current_offset_map[rid] = str(best_offset)

            except Exception as e:
                print(f"calc_current_offset_map 处理路口 {rid} 出错: {e}")
                current_offset_map[rid] = "0"

        return {
            "current_offset_map": current_offset_map,
            "target_offset_map": target_offset_map,
            "cycle_seconds": cycle,
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

        if congestion_direction == "R":
            ref_rid = RIGHT_OFFSET_RID
        elif congestion_direction == "L":
            ref_rid = LEFT_OFFSET_RID
        else:
            print(f"警告: congestion_direction={congestion_direction} 无效，应为 'R' 或 'L'")
            return copy.deepcopy(result_action_map)

        if ref_rid not in result_action_map:
            print(f"警告: result_action_map 中不存在参考路口 {ref_rid}")
            return copy.deepcopy(result_action_map)

        if len(result_action_map[ref_rid]) < 2:
            print(f"警告: 参考路口 {ref_rid} 的方案长度不足，至少需要前两位")
            return copy.deepcopy(result_action_map)

        try:
            cycle = int(cycle_seconds or 0)
            if cycle <= 0:
                cycle = int(result_action_map[ref_rid][0]) + int(result_action_map[ref_rid][1])
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

                if rid not in next_plan or len(next_plan[rid]) < 2:
                    continue

                if rid not in current_offset_map or rid not in target_offset_map:
                    continue

                try:
                    cur_offset = int(current_offset_map[rid])
                    target_offset = int(target_offset_map[rid])
                except Exception as e:
                    print(f"警告: 路口 {rid} 相位差解析失败: {e}")
                    continue

                diff = calc_cyclic_diff(cur_offset, target_offset, cycle)

                if diff > 0:
                    delta = min(int(OFFSET_STEP), diff)
                elif diff < 0:
                    delta = -min(int(OFFSET_STEP), abs(diff))
                else:
                    delta = 0

                old_p1 = int(next_plan[rid][0])
                old_p2 = int(next_plan[rid][1])

                r_i = DEFAULT_RED_DURATIONS.get(rid, 12)
                target_green_sum = max(20, cycle - r_i)

                bounds = PHASE_CHECK_BOUNDS.get(rid, {"p1": (10, 80), "p2": (10, 80)})
                p1_min, p1_max = bounds["p1"]
                p2_min, p2_max = bounds["p2"]

                valid_p1_min = max(p1_min, target_green_sum - p2_max)
                valid_p1_max = min(p1_max, target_green_sum - p2_min)

                gw_idx = GREEN_WAVE_STAGE_INDEX.get(rid, 0)
                if gw_idx == 0:
                    proposed_p1 = old_p1 - delta
                else:
                    proposed_p1 = old_p1 + delta

                new_p1 = max(valid_p1_min, min(valid_p1_max, proposed_p1))
                new_p2 = target_green_sum - new_p1

                next_plan[rid][0] = new_p1
                next_plan[rid][1] = new_p2

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


def apply_green_wave_coordination(
    time_str: str,
    cur_action_map: Dict[str, List[int]],
    result_action_map: Dict[str, List[int]],
    coordinate_map_set: Dict[str, Dict[str, int]],
    extend_map: Optional[Dict[str, Dict[Union[str, int], List[dict]]]] = None,
) -> Dict[str, List[int]]:
    """
    绿波走廊协同控制独立主入口函数：
    处理高峰期检测、状态机维护、走廊周期统一对齐(扣除红灯)、相位差微调及下发冷却保护。
    """
    global start, cycle_green, offset_green, cycle_done, offset_done
    global cnt, fix_plan, direction, green_plan_map, last_green_wave_send_time

    if not time_str or not isinstance(time_str, str):
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    judge1 = is_in_morning_peak_str(time_str)
    judge2 = is_in_evening_peak_str(time_str)

    if judge1:
        alarm_green = True
        alarm_direction = "R"
        print("当前处于早高峰")
    elif judge2:
        alarm_green = True
        alarm_direction = "L"
        print("当前处于晚高峰")
    else:
        alarm_green = False
        alarm_direction = ""
        print("当前未开启绿波")

    # 非绿波时段立即退出，防止旧绿波方案跨时段继续下发。
    if not alarm_green:
        if start:
            print("绿波时段结束，重置绿波状态。")
            reset_green_wave_state()
        return result_action_map

    current_time_sec = time.time()
    if not start:
        start = True
        cycle_green = True
        offset_green = False
        direction = alarm_direction
        cnt = 0
        last_green_wave_send_time = 0
        green_plan_map = {item: cur_action_map[item][:] for item in ORDER if item in cur_action_map}

    if start and REF_RID in green_plan_map:
        working_plan = {
            item: green_plan_map.get(item, cur_action_map[item])[:]
            for item in ORDER
            if item in cur_action_map
        }

        # 检查下发保护冷却时间，防止重发频率高于走廊统一周期 C
        cooldown_passed = (last_green_wave_send_time == 0) or (
            current_time_sec - last_green_wave_send_time >= (DEFAULT_CORRIDOR_CYCLE - 5)
        )

        if not cooldown_passed:
            print(f"绿波冷却中（距离上次调整不足 {DEFAULT_CORRIDOR_CYCLE - 5} 秒），保持当前已下发周期方案。")
            for item in ORDER:
                if item in result_action_map and item in working_plan:
                    result_action_map[item] = working_plan[item][:]
        else:
            # 1. 从 extend 反馈统计各路口红灯总时长 R_i
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
                if cycle_done:
                    cycle_green = False
                    offset_green = True
                last_green_wave_send_time = current_time_sec

            # ------------------------------------ 相位差调整部分 -----------------------------------------------
            elif offset_green:
                res = compute_green_wave_target_offsets(
                    coordinate_map_set=coordinate_map_set,
                    result_action_map=working_plan,
                    congestion_direction=direction,
                    extend_map=extend_map,
                )
                current_offset_map = res.get("current_offset_map", {})
                target_offset_map = res.get("target_offset_map", {})
                cycle_seconds = int(res.get("cycle_seconds", 0) or DEFAULT_CORRIDOR_CYCLE)

                print("目标相位差：", target_offset_map)
                print("当前相位差：", current_offset_map)

                if not current_offset_map or not target_offset_map or cycle_seconds <= 0:
                    print("绿波相位差等待完整 extend 阶段反馈。")
                    for item in ORDER:
                        if item in result_action_map and item in working_plan:
                            result_action_map[item] = working_plan[item][:]
                elif offsets_aligned(
                    current_offset_map, target_offset_map, cycle_seconds
                ):
                    print("绿波相位差已达到目标。保持绿波协同运行。")
                    for item in ORDER:
                        if item in result_action_map and item in working_plan:
                            result_action_map[item] = working_plan[item][:]
                else:
                    next_plan = adjust_offset_one_round(
                        result_action_map=working_plan,
                        current_offset_map=current_offset_map,
                        target_offset_map=target_offset_map,
                        congestion_direction=direction,
                        cycle_seconds=cycle_seconds,
                    )
                    green_plan_map = round_next_plan(next_plan)
                    for item in ORDER:
                        if item in result_action_map and item in green_plan_map:
                            result_action_map[item] = green_plan_map[item][:]
                    last_green_wave_send_time = current_time_sec

    return result_action_map


# 判断是否位于早高峰
def is_in_morning_peak_str(time_str):
    if not time_str or not isinstance(time_str, str):
        return False
    try:
        dt = datetime.strptime(time_str.strip(), "%Y-%m-%d %H:%M:%S")

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
    if not time_str or not isinstance(time_str, str):
        return False
    try:
        dt = datetime.strptime(time_str.strip(), "%Y-%m-%d %H:%M:%S")

        start = dt.replace(hour=17, minute=0, second=0)
        end = dt.replace(hour=22, minute=0, second=0)

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
                timestamp = float(item["time"])
                if timestamp > 1e11:  # 毫秒时间戳转换为秒
                    timestamp = timestamp / 1000.0
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
