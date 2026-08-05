import json
import os
import copy
import math


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.abspath(os.path.join(BASE_DIR, os.pardir))

# ============================================================
# 输入输出文件
# ============================================================

# 输入经验表
biao = "lin_shi_111"
INPUT_PATH = os.path.join(LIB_DIR, biao + ".json")

# 输出补全后的经验表
OUTPUT_PATH = os.path.join(LIB_DIR, biao + "beiyong3.json")

# 路口配置
INFO_PATH = os.path.join(LIB_DIR, "cross_info.json")


# ============================================================
# 可自由选择需要补齐的路口
# ============================================================

ROAD_ID_SET = {
    "1300362",
    "1300068",
    "1300069",
    "1300870",
    "1300044",
    "1300047",
    "1700275",
    "1700086",
    "1700087",
    "1700276",
    "1300239",
    "1300229",
    "2703062",
    "1300106",
    "1300042",
    "1300101",
    "1300092",
    "2712127",
    "1700079",
    "1700125",
    "1700126",
    "1700124",
    "1300166",
    "1300153",
    "1300306",
    "1300409",
    "1700067",
    "1700085",
    "1300147",
    "1700262",
    "1700293",
    "1300087",
    "2702736",
}

# 如果想处理全部路口，改成：
# ROAD_ID_SET = None


# ============================================================
# 方向配置
# ============================================================

BASE_DIRS = ["U", "D", "L", "R"]
LEFT_TURN_DIRS = ["UTL", "DTL", "LTL", "RTL"]


# ============================================================
# 参数区
# ============================================================

# 有效区间保护
MAX_VALID_TIME = 120
MAX_CONSECUTIVE_ZERO = 5#连续0数目

# 边界低值判断
BOUNDARY_LOW_VALUE = 3
BOUNDARY_LOW_RATIO = 0.25
BOUNDARY_WINDOW = 4

# 尾部稀疏低值判断
TAIL_RATIO = 0.40
TAIL_MIN_COUNT = 2

# 局部异常峰判断
LOCAL_WINDOW = 2
SUPPORT_RATIO = 0.90
SPIKE_GAP = 15

# 异常峰修正时，取前后合理中间值
REASONABLE_LOW_RATIO = 0.40

# 平台爬升动态步长
PLATEAU_STEP_MIN = 1
PLATEAU_STEP_MAX = 3
PLATEAU_STEP_RATIO = 0.25

# 不把最大值强行移动到最后一个时间点
MOVE_MAX_TO_LAST_TIME = False

# 所有方向最后统一按时间四区间压缩
TIME_SECTION_RATIOS = [0.90, 0.90, 0.95, 0.95]


# ============================================================
# JSON 工具
# ============================================================

def load_json(path):
    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 基础工具
# ============================================================

def calc_median(values):
    if not values:
        return 0

    values = sorted(float(x) for x in values)
    n = len(values)
    mid = n // 2

    if n % 2 == 1:
        return values[mid]

    return (values[mid - 1] + values[mid]) / 2


def get_base_direction(direction):
    direction = str(direction)

    if direction.endswith("TL"):
        return direction[0]

    return direction


def normalize_flow_list(flow_list):
    result = [0] * 10

    if not isinstance(flow_list, list):
        return result

    for i in range(min(10, len(flow_list))):
        try:
            result[i] = int(round(float(flow_list[i])))
        except Exception:
            result[i] = 0

    return result


def sum_flow(flow_list):
    return sum(normalize_flow_list(flow_list))


# ============================================================
# 有效区间判断
# ============================================================

def get_valid_time_range_from_series(
    dir_data,
    value_func,
    max_time=MAX_VALID_TIME,
    max_consecutive_zero=MAX_CONSECUTIVE_ZERO
):
    """
    根据原始方向数据判断有效时间区间。

    规则：
    1. 只考虑 time <= max_time 的数据；
    2. 原始 JSON 中缺失的中间 time 默认按 0 参与判断；
    3. 只有 time > ZERO_CHECK_START_TIME 之后，才开始判断连续 0；
    4. 如果 time > ZERO_CHECK_START_TIME 后连续 0 超过 max_consecutive_zero 个，
       从这一段连续 0 的第一个 0 前面截断；
    """

    ZERO_CHECK_START_TIME = 40

    raw_map = {}

    for t_key, flow_list in dir_data.items():
        try:
            t = int(t_key)
        except Exception:
            continue

        if t > max_time:
            continue

        try:
            v = int(round(float(value_func(flow_list))))
        except Exception:
            v = 0

        raw_map[t] = v

    if not raw_map:
        return None, None, {
            "reason": "no_items_after_time_filter",
            "max_time": max_time,
            "max_consecutive_zero": max_consecutive_zero,
            "zero_check_start_time": ZERO_CHECK_START_TIME,
            "valid_start_time": None,
            "valid_end_time": None,
            "zero_start_time": None,
            "zero_trigger_time": None,
            "missing_time_as_zero": True,
        }

    min_time = min(raw_map.keys())
    max_existing_time = max(raw_map.keys())

    items = []

    for t in range(min_time, max_existing_time + 1):
        v = raw_map.get(t, 0)
        items.append((t, v))

    valid_start_time = min_time
    valid_end_time = max_existing_time

    zero_count = 0
    zero_start_time = None

    for t, v in items:
        # 40 之前不判断连续 0
        if t <= ZERO_CHECK_START_TIME:
            zero_count = 0
            zero_start_time = None
            continue

        if int(v) == 0:
            if zero_count == 0:
                zero_start_time = t
            zero_count += 1
        else:
            zero_count = 0
            zero_start_time = None

        if zero_count > max_consecutive_zero:
            valid_end_time = zero_start_time - 1

            return valid_start_time, valid_end_time, {
                "reason": "continuous_zero_cut_after_40",
                "max_time": max_time,
                "max_consecutive_zero": max_consecutive_zero,
                "zero_check_start_time": ZERO_CHECK_START_TIME,
                "valid_start_time": valid_start_time,
                "valid_end_time": valid_end_time,
                "zero_start_time": zero_start_time,
                "zero_trigger_time": t,
                "missing_time_as_zero": True,
            }

    return valid_start_time, valid_end_time, {
        "reason": "normal",
        "max_time": max_time,
        "max_consecutive_zero": max_consecutive_zero,
        "zero_check_start_time": ZERO_CHECK_START_TIME,
        "valid_start_time": valid_start_time,
        "valid_end_time": valid_end_time,
        "zero_start_time": None,
        "zero_trigger_time": None,
        "missing_time_as_zero": True,
    }

def filter_dir_data_by_valid_range(dir_data, valid_start_time, valid_end_time):
    """
    只保留有效时间区间内的原始方向数据。
    """
    if valid_start_time is None or valid_end_time is None:
        return {}

    result = {}

    for t_key, flow_list in dir_data.items():
        try:
            t = int(t_key)
        except Exception:
            continue

        if valid_start_time <= t <= valid_end_time:
            result[str(t)] = copy.deepcopy(flow_list)

    return result


# ============================================================
# 找 1C 车道
# ============================================================

def find_left_turn_lane_index(cross_info, road_id, left_turn_dir):
    road_id = str(road_id)

    if road_id not in cross_info:
        return None

    if "LaneNo" not in cross_info[road_id]:
        return None

    base_dir = get_base_direction(left_turn_dir)
    lane_info = cross_info[road_id]["LaneNo"].get(base_dir, {})

    for lane_no, lane_type in lane_info.items():
        if str(lane_type).upper() == "1C":
            try:
                lane_idx = int(lane_no)
            except Exception:
                continue

            if 0 <= lane_idx <= 9:
                return lane_idx

    return None


# ============================================================
# 排序
# ============================================================

def sort_by_time(data):
    sorted_data = {}

    for road_id, directions in data.items():
        sorted_data[road_id] = {}

        for direction, time_dict in directions.items():
            sorted_data[road_id][direction] = {}

            sorted_times = sorted(time_dict.keys(), key=int)

            for t in sorted_times:
                sorted_data[road_id][direction][t] = time_dict[t]

    return sorted_data


# ============================================================
# 边界稀疏处理
# ============================================================

def trim_sparse_boundary_points(
    times,
    vals,
    boundary_window=BOUNDARY_WINDOW,
    low_value=BOUNDARY_LOW_VALUE,
    low_ratio=BOUNDARY_LOW_RATIO
):
    if not times or not vals:
        return times, vals, 0, 0

    pairs = list(zip(times, vals))
    positive_vals = [float(v) for v in vals if float(v) > 0]

    if not positive_vals:
        return times, vals, 0, 0

    median_val = calc_median(positive_vals)
    threshold = max(low_value, median_val * low_ratio)

    left = 0
    right = len(pairs) - 1

    while left <= right:
        v = float(pairs[left][1])

        if left < boundary_window and v <= threshold:
            left += 1
        else:
            break

    while right >= left:
        v = float(pairs[right][1])

        if len(pairs) - 1 - right < boundary_window and v <= threshold:
            right -= 1
        else:
            break

    trimmed = pairs[left:right + 1]

    if not trimmed:
        return times, vals, 0, 0

    trimmed_times = [x[0] for x in trimmed]
    trimmed_vals = [x[1] for x in trimmed]

    removed_left = left
    removed_right = len(pairs) - 1 - right

    return trimmed_times, trimmed_vals, removed_left, removed_right


def trim_tail_sparse_by_peak(
    times,
    vals,
    peak_val,
    tail_ratio=TAIL_RATIO,
    min_tail_count=TAIL_MIN_COUNT
):
    if not times or not vals:
        return times, vals, 0

    threshold = float(peak_val) * tail_ratio

    cut_count = 0
    i = len(vals) - 1

    while i >= 0:
        if float(vals[i]) <= threshold:
            cut_count += 1
            i -= 1
        else:
            break

    if cut_count >= min_tail_count:
        keep_len = len(vals) - cut_count
        return times[:keep_len], vals[:keep_len], cut_count

    return times, vals, 0


# ============================================================
# 异常峰处理
# ============================================================

def calc_reasonable_middle_value(
    neighbor_vals,
    cur_val,
    reasonable_low_ratio=REASONABLE_LOW_RATIO
):
    if not neighbor_vals:
        return cur_val

    cur_val = float(cur_val)
    threshold = cur_val * reasonable_low_ratio

    reasonable_vals = [
        float(v)
        for v in neighbor_vals
        if float(v) >= threshold
    ]

    if reasonable_vals:
        return calc_median(reasonable_vals)

    return calc_median(neighbor_vals)


def reduce_local_unstable_peaks_by_middle(
    times,
    vals,
    window=LOCAL_WINDOW,
    support_ratio=SUPPORT_RATIO,
    spike_gap=SPIKE_GAP
):
    if not times or not vals:
        return vals, []

    n = len(vals)
    new_vals = [float(v) for v in vals]
    changed_points = []

    for i in range(n):
        cur_time = int(times[i])
        cur_val = float(vals[i])

        if cur_val <= 0:
            continue

        left = max(0, i - window)
        right = min(n, i + window + 1)

        neighbor_vals = [
            float(vals[j])
            for j in range(left, right)
            if j != i
        ]

        if not neighbor_vals:
            continue

        local_median = calc_median(neighbor_vals)

        has_support = any(
            v >= cur_val * support_ratio
            for v in neighbor_vals
        )

        too_high = cur_val - local_median >= spike_gap
        is_unstable_peak = (not has_support) and too_high

        if not is_unstable_peak:
            continue

        reduced_val = calc_reasonable_middle_value(
            neighbor_vals=neighbor_vals,
            cur_val=cur_val,
            reasonable_low_ratio=REASONABLE_LOW_RATIO
        )

        reduced_val = min(reduced_val, cur_val)
        reduced_val = int(round(reduced_val))

        new_vals[i] = reduced_val

        changed_points.append({
            "time": cur_time,
            "old": int(round(cur_val)),
            "new": reduced_val,
            "local_median": round(float(local_median), 2),
            "neighbors": [int(round(x)) for x in neighbor_vals],
            "has_support": has_support
        })

    new_vals = [int(round(x)) for x in new_vals]

    return new_vals, changed_points


def get_reliable_peak_value(times, vals):
    if not times or not vals:
        return None

    positive_vals = [float(v) for v in vals if float(v) > 0]

    if not positive_vals:
        return None

    return max(positive_vals)


# ============================================================
# 最大值后移
# ============================================================

def move_max_value_to_last_time(
    trusted_times,
    trusted_vals,
    all_times,
    original_max_value
):
    if not trusted_times or not trusted_vals or not all_times:
        return trusted_times, trusted_vals

    original_max_value = float(original_max_value)
    last_time = max(int(t) for t in all_times)

    new_pairs = []

    for t, v in zip(trusted_times, trusted_vals):
        t = int(t)
        v = float(v)

        if t != last_time and v >= original_max_value:
            continue

        new_pairs.append((t, v))

    merged = {}

    for t, v in new_pairs:
        merged[int(t)] = float(v)

    merged[last_time] = original_max_value

    final_pairs = sorted(merged.items(), key=lambda x: int(x[0]))

    new_times = [int(t) for t, _ in final_pairs]
    new_vals = [float(v) for _, v in final_pairs]

    return new_times, new_vals


# ============================================================
# 平台爬升
# ============================================================

def calc_dynamic_plateau_step(
    trusted_vals,
    min_step=PLATEAU_STEP_MIN,
    max_step=PLATEAU_STEP_MAX,
    ratio=PLATEAU_STEP_RATIO
):
    vals = [float(v) for v in trusted_vals if float(v) > 0]

    if len(vals) < 2:
        return min_step

    vals = sorted(vals)

    start_idx = len(vals) // 2
    high_vals = vals[start_idx:]

    if len(high_vals) < 2:
        return min_step

    diffs = []

    for a, b in zip(high_vals, high_vals[1:]):
        diff = b - a

        if diff > 0:
            diffs.append(diff)

    if not diffs:
        return min_step

    diff_median = calc_median(diffs)

    step = int(round(diff_median * ratio))
    step = max(min_step, step)
    step = min(max_step, step)

    return step


def add_small_rise_to_plateaus(
    fill_map,
    max_allowed_value,
    plateau_step
):
    if not fill_map:
        return fill_map

    times = sorted(int(t) for t in fill_map.keys())

    result = {}
    last_value = None

    max_allowed_value = int(round(float(max_allowed_value)))

    for t in times:
        cur_value = int(round(fill_map[t]))
        cur_value = min(cur_value, max_allowed_value)

        if last_value is None:
            result[t] = cur_value
            last_value = cur_value
            continue

        if cur_value > last_value:
            result[t] = cur_value
            last_value = cur_value
            continue

        candidate = last_value + plateau_step
        candidate = min(candidate, max_allowed_value)
        candidate = max(candidate, last_value)

        result[t] = candidate
        last_value = candidate

    return result


# ============================================================
# 时间四区间压缩
# ============================================================

def apply_time_section_ratios(fill_map, section_ratios=TIME_SECTION_RATIOS):
    if not fill_map:
        return fill_map

    times = sorted(int(t) for t in fill_map.keys())
    n = len(times)

    if n == 0:
        return fill_map

    section_count = len(section_ratios)

    result = {}

    for idx, t in enumerate(times):
        section_idx = int(idx * section_count / n)

        if section_idx >= section_count:
            section_idx = section_count - 1

        ratio = section_ratios[section_idx]

        result[t] = int(round(float(fill_map[t]) * ratio))

    return result


# ============================================================
# 完整补全
# ============================================================

def build_monotone_fill_values(
    all_times,
    trusted_times,
    trusted_vals,
    max_allowed_value
):
    if not all_times:
        return {}

    if not trusted_times or not trusted_vals:
        return {}

    max_allowed_value = float(max_allowed_value)

    pairs = sorted(zip(trusted_times, trusted_vals), key=lambda x: int(x[0]))

    mono_pairs = []
    current_max = None

    for t, v in pairs:
        t = int(t)
        v = float(v)

        if current_max is None:
            current_max = v
        else:
            current_max = max(current_max, v)

        current_max = min(current_max, max_allowed_value)

        mono_pairs.append((t, current_max))

    trusted_map = {
        int(t): float(v)
        for t, v in mono_pairs
    }

    all_times = sorted(int(t) for t in all_times)

    min_trusted_time = mono_pairs[0][0]
    max_trusted_time = mono_pairs[-1][0]

    result = {}

    for t in all_times:

        if t in trusted_map:
            result[t] = trusted_map[t]
            continue

        if t < min_trusted_time:
            result[t] = mono_pairs[0][1]
            continue

        if t > max_trusted_time:
            result[t] = mono_pairs[-1][1]
            continue

        prev_t = None
        prev_v = None
        next_t = None
        next_v = None

        for mt, mv in mono_pairs:
            if mt < t:
                prev_t = mt
                prev_v = mv
            elif mt > t:
                next_t = mt
                next_v = mv
                break

        if prev_t is None:
            result[t] = mono_pairs[0][1]
            continue

        if next_t is None:
            result[t] = mono_pairs[-1][1]
            continue

        if next_t == prev_t:
            result[t] = prev_v
            continue

        ratio = (t - prev_t) / (next_t - prev_t)

        value = prev_v + (next_v - prev_v) * ratio
        value = max(value, prev_v)
        value = min(value, max_allowed_value)

        result[t] = value

    final_result = {}
    current_max = None

    for t in all_times:
        v = float(result[t])

        if current_max is None:
            current_max = v
        else:
            current_max = max(current_max, v)

        current_max = min(current_max, max_allowed_value)
        final_result[t] = int(round(current_max))

    dynamic_step = calc_dynamic_plateau_step(
        trusted_vals=trusted_vals,
        min_step=PLATEAU_STEP_MIN,
        max_step=PLATEAU_STEP_MAX,
        ratio=PLATEAU_STEP_RATIO
    )

    final_result = add_small_rise_to_plateaus(
        fill_map=final_result,
        max_allowed_value=max_allowed_value,
        plateau_step=dynamic_step
    )

    return final_result


# ============================================================
# 公共：单序列补全
# ============================================================

def build_clean_fill_map_from_series(times, vals):
    """
    注意：
    这里不再做 time > 100 或连续 0 删除。
    有效区间已经在方向级别判断好了。

    这里只负责：
    1. 边界稀疏处理
    2. 异常峰削减
    3. 尾部40%低值剔除
    4. 再次异常峰削减
    5. 可选最大值后移
    6. 完整补全
    7. 平台爬升
    8. 时间四区间压缩
    """
    if not times or not vals:
        return {}, {}

    positive_vals = [v for v in vals if v > 0]

    if not positive_vals:
        return {}, {}

    original_max_value = max(positive_vals)
    max_allowed_value = original_max_value

    full_times = list(range(min(times), max(times) + 1))

    times1, vals1, removed_left, removed_right = trim_sparse_boundary_points(
        times=times,
        vals=vals,
        boundary_window=BOUNDARY_WINDOW,
        low_value=BOUNDARY_LOW_VALUE,
        low_ratio=BOUNDARY_LOW_RATIO
    )

    if not times1:
        return {}, {}

    vals2, changed_peaks1 = reduce_local_unstable_peaks_by_middle(
        times=times1,
        vals=vals1,
        window=LOCAL_WINDOW,
        support_ratio=SUPPORT_RATIO,
        spike_gap=SPIKE_GAP
    )

    reliable_peak_val = get_reliable_peak_value(
        times=times1,
        vals=vals2
    )

    if reliable_peak_val is None:
        return {}, {}

    times3, vals3, tail_cut_count = trim_tail_sparse_by_peak(
        times=times1,
        vals=vals2,
        peak_val=reliable_peak_val,
        tail_ratio=TAIL_RATIO,
        min_tail_count=TAIL_MIN_COUNT
    )

    if not times3:
        return {}, {}

    vals4, changed_peaks2 = reduce_local_unstable_peaks_by_middle(
        times=times3,
        vals=vals3,
        window=LOCAL_WINDOW,
        support_ratio=SUPPORT_RATIO,
        spike_gap=SPIKE_GAP
    )

    moved_max_to_last = False

    if MOVE_MAX_TO_LAST_TIME:
        before_times = list(times3)
        before_vals = list(vals4)

        times3, vals4 = move_max_value_to_last_time(
            trusted_times=times3,
            trusted_vals=vals4,
            all_times=full_times,
            original_max_value=original_max_value
        )

        moved_max_to_last = (
            before_times != times3 or
            before_vals != vals4
        )

    fill_map = build_monotone_fill_values(
        all_times=full_times,
        trusted_times=times3,
        trusted_vals=vals4,
        max_allowed_value=max_allowed_value
    )

    if not fill_map:
        return {}, {}

    fill_map = apply_time_section_ratios(
        fill_map=fill_map,
        section_ratios=TIME_SECTION_RATIOS
    )

    debug_info = {
        "original_max": original_max_value,
        "section_ratios": TIME_SECTION_RATIOS,
        "removed_left": removed_left,
        "removed_right": removed_right,
        "tail_cut": tail_cut_count,
        "changed_peaks": changed_peaks1 + changed_peaks2,
        "moved_max_to_last": moved_max_to_last,
    }

    return fill_map, debug_info


# ============================================================
# 主方向数组缩放
# ============================================================

def scale_array_to_target_sum(flow_list, target_sum):
    arr = normalize_flow_list(flow_list)

    target_sum = int(round(float(target_sum)))

    if target_sum <= 0:
        return [0] * 10

    old_sum = sum(arr)

    if old_sum <= 0:
        result = [0] * 10
        result[0] = target_sum
        return result

    raw_values = [
        x * target_sum / old_sum
        for x in arr
    ]

    floors = [int(math.floor(x)) for x in raw_values]
    diff = target_sum - sum(floors)

    fractions = [
        (i, raw_values[i] - floors[i])
        for i in range(10)
    ]

    fractions.sort(key=lambda x: x[1], reverse=True)

    result = floors[:]

    for i in range(diff):
        idx = fractions[i % 10][0]
        result[idx] += 1

    return result


def choose_anchor_array_by_target(dir_data, target_time, target_sum):
    if not dir_data:
        return [0] * 10

    best_arr = None
    best_score = None

    for t_key, flow_list in dir_data.items():
        t = int(t_key)
        arr = normalize_flow_list(flow_list)
        s = sum(arr)

        score = (
            abs(s - target_sum),
            abs(t - target_time)
        )

        if best_score is None or score < best_score:
            best_score = score
            best_arr = arr

    if best_arr is None:
        return [0] * 10

    return best_arr


# ============================================================
# U / D / L / R 补全
# ============================================================

def complete_one_base_direction(road_data, direction):
    """
    U / D / L / R：

    1. 先判断有效区间；
       注意：缺失的中间 time 会默认按 0 参与连续 0 判断。
    2. 只取有效区间内的数据；
    3. 只在有效区间内补全；
    4. 最终只保存有效区间内的补全结果。
    """
    if direction not in road_data:
        return road_data

    original_dir_data = road_data[direction]

    if not original_dir_data:
        return road_data

    valid_start_time, valid_end_time, valid_range_info = get_valid_time_range_from_series(
        dir_data=original_dir_data,
        value_func=sum_flow,
        max_time=MAX_VALID_TIME,
        max_consecutive_zero=MAX_CONSECUTIVE_ZERO
    )

    if valid_start_time is None or valid_end_time is None:
        print(f"主方向无有效区间，清空: dir={direction}, info={valid_range_info}")
        road_data[direction] = {}
        return road_data

    if valid_end_time < valid_start_time:
        print(f"主方向有效区间为空，清空: dir={direction}, info={valid_range_info}")
        road_data[direction] = {}
        return road_data

    valid_dir_data = filter_dir_data_by_valid_range(
        dir_data=original_dir_data,
        valid_start_time=valid_start_time,
        valid_end_time=valid_end_time
    )

    if not valid_dir_data:
        print(f"主方向有效区间内无数据，清空: dir={direction}, info={valid_range_info}")
        road_data[direction] = {}
        return road_data

    items = sorted(valid_dir_data.items(), key=lambda x: int(x[0]))

    times = [int(t) for t, _ in items]
    vals = [
        sum_flow(flow_list)
        for _, flow_list in items
    ]

    fill_map, debug_info = build_clean_fill_map_from_series(
        times=times,
        vals=vals
    )

    if not fill_map:
        print(
            f"主方向补全为空，仅保存有效区间原始数据: "
            f"dir={direction}, valid_range={valid_range_info}"
        )
        road_data[direction] = valid_dir_data
        return road_data

    fill_map = {
        int(t): v
        for t, v in fill_map.items()
        if valid_start_time <= int(t) <= valid_end_time
    }

    new_dir_data = {}

    for t, target_sum in fill_map.items():
        anchor_arr = choose_anchor_array_by_target(
            dir_data=valid_dir_data,
            target_time=t,
            target_sum=target_sum
        )

        new_arr = scale_array_to_target_sum(
            flow_list=anchor_arr,
            target_sum=target_sum
        )

        new_dir_data[str(t)] = new_arr

    road_data[direction] = new_dir_data

    print(
        f"主方向补全完成: dir={direction}, "
        f"valid_range={valid_range_info}, "
        f"original_max={debug_info.get('original_max')}, "
        f"section_ratios={debug_info.get('section_ratios')}, "
        f"removed_left={debug_info.get('removed_left')}, "
        f"removed_right={debug_info.get('removed_right')}, "
        f"tail_cut={debug_info.get('tail_cut')}, "
        f"moved_max_to_last={debug_info.get('moved_max_to_last')}"
    )

    if debug_info.get("changed_peaks"):
        print("    主方向异常峰削减:")
        for item in debug_info["changed_peaks"]:
            print(
                f"        time={item['time']}  "
                f"old={item['old']} -> new={item['new']}  "
                f"neighbors={item['neighbors']}  "
                f"local_median={item['local_median']}"
            )

    return road_data


# ============================================================
# UTL / DTL / LTL / RTL 补全
# ============================================================

def choose_nearest_existing_array(dir_data, target_time):
    if not dir_data:
        return [0] * 10

    best_t = None
    best_arr = None

    for t_key, flow_list in dir_data.items():
        t = int(t_key)
        arr = normalize_flow_list(flow_list)

        if best_t is None or abs(t - target_time) < abs(best_t - target_time):
            best_t = t
            best_arr = arr

    if best_arr is None:
        return [0] * 10

    return best_arr


def complete_one_left_turn_direction(road_data, cross_info, road_id, left_turn_dir):
    """
    UTL / DTL / LTL / RTL：

    1. 找 1C 车道；
    2. 根据 1C 车道判断有效区间；
       注意：缺失的中间 time 会默认按 0 参与连续 0 判断。
    3. 只取有效区间内的数据；
    4. 只在有效区间内补全；
    5. 最终只保存有效区间内的补全结果。
    """
    if left_turn_dir not in road_data:
        return road_data

    original_dir_data = road_data[left_turn_dir]

    if not original_dir_data:
        return road_data

    lane_idx = find_left_turn_lane_index(
        cross_info=cross_info,
        road_id=road_id,
        left_turn_dir=left_turn_dir
    )

    if lane_idx is None:
        print(f"未找到1C车道，跳过: road_id={road_id}, dir={left_turn_dir}")
        return road_data

    def get_left_lane_value(flow_list):
        arr = normalize_flow_list(flow_list)

        if lane_idx < 0 or lane_idx >= len(arr):
            return 0

        return arr[lane_idx]

    valid_start_time, valid_end_time, valid_range_info = get_valid_time_range_from_series(
        dir_data=original_dir_data,
        value_func=get_left_lane_value,
        max_time=MAX_VALID_TIME,
        max_consecutive_zero=MAX_CONSECUTIVE_ZERO
    )

    if valid_start_time is None or valid_end_time is None:
        print(
            f"左转无有效区间，清空: road_id={road_id}, "
            f"dir={left_turn_dir}, lane_idx={lane_idx}, info={valid_range_info}"
        )
        road_data[left_turn_dir] = {}
        return road_data

    if valid_end_time < valid_start_time:
        print(
            f"左转有效区间为空，清空: road_id={road_id}, "
            f"dir={left_turn_dir}, lane_idx={lane_idx}, info={valid_range_info}"
        )
        road_data[left_turn_dir] = {}
        return road_data

    valid_dir_data = filter_dir_data_by_valid_range(
        dir_data=original_dir_data,
        valid_start_time=valid_start_time,
        valid_end_time=valid_end_time
    )

    if not valid_dir_data:
        print(
            f"左转有效区间内无数据，清空: road_id={road_id}, "
            f"dir={left_turn_dir}, lane_idx={lane_idx}, info={valid_range_info}"
        )
        road_data[left_turn_dir] = {}
        return road_data

    items = sorted(valid_dir_data.items(), key=lambda x: int(x[0]))

    times = []
    vals = []

    for t_key, flow_list in items:
        t = int(t_key)
        arr = normalize_flow_list(flow_list)

        times.append(t)
        vals.append(arr[lane_idx])

    fill_map, debug_info = build_clean_fill_map_from_series(
        times=times,
        vals=vals
    )

    if not fill_map:
        print(
            f"左转补全为空，仅保存有效区间原始数据: road_id={road_id}, "
            f"dir={left_turn_dir}, lane_idx={lane_idx}, "
            f"valid_range={valid_range_info}"
        )
        road_data[left_turn_dir] = valid_dir_data
        return road_data

    fill_map = {
        int(t): v
        for t, v in fill_map.items()
        if valid_start_time <= int(t) <= valid_end_time
    }

    new_dir_data = {}

    for t, target_val in fill_map.items():
        t_key = str(t)

        if t_key in valid_dir_data:
            arr = normalize_flow_list(valid_dir_data[t_key])
        else:
            arr = choose_nearest_existing_array(
                dir_data=valid_dir_data,
                target_time=t
            )

        arr[lane_idx] = int(round(target_val))
        new_dir_data[t_key] = arr

    road_data[left_turn_dir] = new_dir_data

    print(
        f"左转补全完成: road_id={road_id}, dir={left_turn_dir}, "
        f"lane_idx={lane_idx}, "
        f"valid_range={valid_range_info}, "
        f"original_max={debug_info.get('original_max')}, "
        f"section_ratios={debug_info.get('section_ratios')}, "
        f"removed_left={debug_info.get('removed_left')}, "
        f"removed_right={debug_info.get('removed_right')}, "
        f"tail_cut={debug_info.get('tail_cut')}, "
        f"moved_max_to_last={debug_info.get('moved_max_to_last')}"
    )

    if debug_info.get("changed_peaks"):
        print("    左转异常峰削减:")
        for item in debug_info["changed_peaks"]:
            print(
                f"        time={item['time']}  "
                f"old={item['old']} -> new={item['new']}  "
                f"neighbors={item['neighbors']}  "
                f"local_median={item['local_median']}"
            )

    return road_data


# ============================================================
# 单路口处理
# ============================================================

def complete_one_road(data, cross_info, road_id):
    road_id = str(road_id)

    if road_id not in data:
        print(f"经验表中没有该路口，跳过: road_id={road_id}")
        return data

    if road_id not in cross_info:
        print(f"cross_info.json 中没有该路口，跳过: road_id={road_id}")
        return data

    road_data = data[road_id]

    for direction in BASE_DIRS:
        road_data = complete_one_base_direction(
            road_data=road_data,
            direction=direction
        )

    for direction in LEFT_TURN_DIRS:
        road_data = complete_one_left_turn_direction(
            road_data=road_data,
            cross_info=cross_info,
            road_id=road_id,
            left_turn_dir=direction
        )

    data[road_id] = road_data

    return data


# ============================================================
# 主程序
# ============================================================

def main():
    data = load_json(INPUT_PATH)
    cross_info = load_json(INFO_PATH)

    if not data:
        print(f"经验表为空或不存在: {INPUT_PATH}")
        return

    if not cross_info:
        print(f"cross_info.json 为空或不存在: {INFO_PATH}")
        return

    result = copy.deepcopy(data)

    if ROAD_ID_SET is None:
        road_ids = list(result.keys())
    else:
        road_ids = [str(x) for x in ROAD_ID_SET]

    for road_id in road_ids:
        print("=" * 100)
        print(f"开始补齐路口: {road_id}")

        result = complete_one_road(
            data=result,
            cross_info=cross_info,
            road_id=road_id
        )

    result = sort_by_time(result)

    save_json(OUTPUT_PATH, result)

    print("=" * 100)
    print("经验表补齐完成")
    print(f"输入文件: {INPUT_PATH}")
    print(f"输出文件: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
