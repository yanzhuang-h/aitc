import json
import time
import os
import tempfile
from collections import Counter
from datetime import datetime, timedelta

try:
    from lib.data_ANS.raw_data_cleaning import (
        DEFAULT_MAX_STAGE_GAP_SECONDS,
        clean_training_inputs,
    )
    from lib.data_ANS.experience_candidate_audit import ExperienceCandidateAudit
    from lib.data_ANS.lane_policy import (
        capacity_experience_direction,
        classify_lane_type,
        is_dedicated_left,
    )
    from lib.data_ANS.cycle_quality import (
        CYCLE_OBSERVATION_WINDOW_SECONDS,
        LONG_CYCLE_THRESHOLD_SECONDS,
        MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        MIN_CONSECUTIVE_CYCLES,
        WINDOW_SECONDS,
        centered_observation_bounds,
        cycle_observation_expansion_decision,
        group_consecutive_same_pattern_cycles,
        split_cycle_group_on_stage_change,
    )
except ModuleNotFoundError:
    from raw_data_cleaning import (
        DEFAULT_MAX_STAGE_GAP_SECONDS,
        clean_training_inputs,
    )
    from experience_candidate_audit import ExperienceCandidateAudit
    from lane_policy import (
        capacity_experience_direction,
        classify_lane_type,
        is_dedicated_left,
    )
    from cycle_quality import (
        CYCLE_OBSERVATION_WINDOW_SECONDS,
        LONG_CYCLE_THRESHOLD_SECONDS,
        MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        MIN_CONSECUTIVE_CYCLES,
        WINDOW_SECONDS,
        centered_observation_bounds,
        cycle_observation_expansion_decision,
        group_consecutive_same_pattern_cycles,
        split_cycle_group_on_stage_change,
    )


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.abspath(os.path.join(BASE_DIR, os.pardir))
PROJECT_ROOT = os.path.abspath(os.path.join(LIB_DIR, os.pardir))
JIYAN_PATH = os.environ.get(
    "AITC_EXPERIENCE_OUTPUT",
    os.path.join(LIB_DIR, "lin_shi_11123.json"),
)
INFO_PATH = os.path.join(LIB_DIR, "cross_info.json")


with open(INFO_PATH, "r", encoding="utf-8") as f:
    lines3 = json.load(f)


# ============================================================
# 配置区
# ============================================================
datas = [
'2026-07-01',
'2026-06-29',
'2026-06-28',
'2026-06-27',
'2026-06-17',
'2026-06-18',
'2026-06-19',
'2026-06-20',
'2026-06-21',
'2026-06-22',
# '2026-04-08',
# '2026-04-07',
# '2026-03-19',
# '2026-03-20',
# '2026-03-16',
# '2026-03-15',
# '2026-03-14',
# '2026-03-13',
# '2026-03-12',
# '2026-03-11',
# (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
]
configured_dates = os.environ.get("AITC_TRAIN_DATES", "").strip()
if configured_dates:
    datas = [value.strip() for value in configured_dates.split(",") if value.strip()]


shipin_roid = {
    "1300069",
    "1300068",
    "1300067",
    "1700125",
}
configured_road_ids = os.environ.get("AITC_TRAIN_ROAD_IDS", "").strip()
if configured_road_ids:
    shipin_roid = {
        value.strip()
        for value in configured_road_ids.split(",")
        if value.strip()
    }

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
TRAIN_VERBOSE = os.environ.get("AITC_TRAIN_VERBOSE", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FILTER_UNAVAILABLE_DIRECTIONS = os.environ.get(
    "AITC_TRAIN_FILTER_UNAVAILABLE_DIRECTIONS",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}


# ============================================================
# 通用函数
# ============================================================

def get_time_sec(t):
    """
    【函数作用】
    兼容秒级和毫秒级时间戳。

    【说明】
    13 位毫秒时间戳会除以 1000；
    10 位秒级时间戳直接返回。
    """
    t = int(t)

    if t > 10_000_000_000:
        return t // 1000

    return t


def fmt_time(ts):
    """
    【函数作用】
    秒级时间戳转可读时间。
    """
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))


def debug_print(*args, **kwargs):
    if TRAIN_VERBOSE:
        print(*args, **kwargs)


def write_json_atomic(file_path, data):
    """Atomically replace a JSON file after the complete payload is written."""
    directory = os.path.dirname(os.path.abspath(file_path))
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            delete=False,
        ) as file:
            temp_path = file.name
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, file_path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def load_result(file_path):
    """
    【函数作用】
    读取 json 文件。
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_json(data, road_id):
    """
    【函数作用】
    保存某个路口的经验表到 lin_shi.json。
    """
    if not os.path.exists(JIYAN_PATH):
        print("经验表文件不存在:", JIYAN_PATH)
        return {}

    with open(JIYAN_PATH, "r", encoding="utf-8") as f:
        data_old = json.load(f)

    data_old[road_id] = data

    write_json_atomic(JIYAN_PATH, sort_by_time(data_old))


def load_json(road_id):
    """
    【函数作用】
    读取某个路口旧的经验表。
    """
    if not os.path.exists(JIYAN_PATH):
        print("经验表文件不存在:", JIYAN_PATH)
        return {}

    with open(JIYAN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if road_id not in data:
        return {}

    return data[road_id]


def sort_by_time(data):
    """
    【函数作用】
    对经验表中每个方向的时间 key 进行排序。
    """
    sorted_data = {}

    for cross_id, directions in data.items():
        sorted_data[cross_id] = {}

        for direction, time_dict in directions.items():
            sorted_data[cross_id][direction] = {}

            sorted_times = sorted(time_dict.keys(), key=int)

            for time_key in sorted_times:
                sorted_data[cross_id][direction][str(time_key)] = time_dict[time_key]

    return sorted_data


def sort_zhong():
    """
    【函数作用】
    对 lin_shi.json 里的时间 key 排序。
    """
    save_path = JIYAN_PATH
    result_data = load_result(save_path)
    sorted_result = sort_by_time(result_data)

    write_json_atomic(save_path, sorted_result)

    print("排序完成已保存")


def save_experience_table(data):
    sorted_result = sort_by_time(data)
    write_json_atomic(JIYAN_PATH, sorted_result)
    return sorted_result


def merge_zhongbiao(old_data: dict, new_data: dict, road_id) -> dict:
    """
    【函数作用】
    合并旧经验表和新经验表。

    【合并规则】
    如果同方向、同时间已经存在，则保留总车流更大的那一组。
    """
    if old_data == {}:
        return new_data

    for d, value in new_data.items():
        if d not in old_data:
            old_data[d] = {}

        for i in value:
            if str(i) not in old_data[d]:
                old_data[d][str(i)] = value[i]
            else:
                if sum(old_data[d][str(i)]) < sum(value[i]):
                    old_data[d][str(i)] = value[i]

    return old_data


# ============================================================
# 周期配置读取函数
# ============================================================

def get_cycle_patterns_from_cross_info(road_id):
    """
    【函数作用】
    从 cross_info.json 中读取指定路口的 Cycle 周期配置。

    【cross_info.json 格式示例】
    "Cycle": [
        [1, 2, 3, 4],
        [1, 2, 3, 4, 5],
        [501, 506, 508, 509, 502]
    ]

    【返回格式】
    [
        ["1", "2", "3", "4"],
        ["1", "2", "3", "4", "5"],
        ["501", "506", "508", "509", "502"]
    ]

    【说明】
    全部转成字符串，是为了和 phase_intervals 里的 item["stage"] 保持一致。
    """
    road_id = str(road_id)

    if road_id not in lines3:
        print(f"cross_info.json 中不存在路口: road_id={road_id}")
        return []

    Cycle = lines3[road_id].get("Cycle", [])

    if not Cycle:
        print(f"cross_info.json 中该路口未配置 Cycle: road_id={road_id}")
        return []

    patterns = []

    for pattern in Cycle:
        if not isinstance(pattern, list):
            continue

        pattern_str = [str(x) for x in pattern]

        if pattern_str:
            patterns.append(pattern_str)

    # 【重要】
    # 长周期放前面，避免短周期是长周期前缀时提前匹配。
    # 例如：
    # [1,2,3,4,5]
    # [1,2,3,4]
    patterns.sort(key=lambda x: len(x), reverse=True)

    return patterns


# ============================================================
# 阶段处理函数
# ============================================================

def build_continuous_phase_dict(dict_id_raw):
    """
    【函数作用】
    把原始阶段数据补成连续秒级阶段表。

    【规则】
    1. -1 归到上一个有效阶段。
    2. 缺失秒也沿用上一个有效阶段。
    3. 如果开头就是 -1，没有上一个有效阶段，则保留 -1。

    【用途】
    生成的 dict_id_filled 用于压缩阶段执行区间。
    """
    if not dict_id_raw:
        return {}

    result = {}

    sorted_ts = sorted(dict_id_raw.keys())

    start_ts = sorted_ts[0]
    end_ts = sorted_ts[-1]

    last_valid_phase = None

    raw_map = {
        int(ts): str(phase)
        for ts, phase in dict_id_raw.items()
    }

    for ts in range(start_ts, end_ts + 1):
        if ts in raw_map:
            phase = raw_map[ts]

            if phase != "-1":
                last_valid_phase = phase
                result[ts] = phase
            else:
                if last_valid_phase is not None:
                    result[ts] = last_valid_phase
                else:
                    result[ts] = "-1"
        else:
            if last_valid_phase is not None:
                result[ts] = last_valid_phase
            else:
                result[ts] = "-1"

    return result


def compress_phase_intervals(phase_dict):
    """
    【函数作用】
    把连续秒级阶段表压缩成阶段执行区间。

    【返回】
    [
        {
            "stage": 阶段号,
            "start": 开始时间,
            "end": 结束时间,
            "duration": 执行时间秒数
        }
    ]
    """
    if not phase_dict:
        return []

    intervals = []

    items = sorted(phase_dict.items(), key=lambda x: x[0])

    cur_stage = None
    cur_start = None
    last_ts = None

    for ts, stage in items:
        ts = int(ts)
        stage = str(stage)

        if cur_stage is None:
            cur_stage = stage
            cur_start = ts
            last_ts = ts
            continue

        if stage == cur_stage and ts == last_ts + 1:
            last_ts = ts
            continue

        intervals.append({
            "stage": cur_stage,
            "start": cur_start,
            "end": last_ts,
            "duration": last_ts - cur_start + 1
        })

        cur_stage = stage
        cur_start = ts
        last_ts = ts

    if cur_stage is not None:
        intervals.append({
            "stage": cur_stage,
            "start": cur_start,
            "end": last_ts,
            "duration": last_ts - cur_start + 1
        })

    last_index = len(intervals) - 1
    for index, interval in enumerate(intervals):
        interval["layer_index"] = index
        interval["data_boundary_partial"] = index in (0, last_index)

    return intervals


def find_complete_cycles_from_intervals(intervals, patterns, start_time, end_time):
    """
    【函数作用】
    从阶段区间中，按 cross_info.json 中配置的多个 Cycle 模板，
    抽取窗口内的全部完整周期，训练时至少需要 3 个有效周期。

    【参数】
    patterns:
        [
            ["1", "2", "3", "4", "5"],
            ["1", "2", "3", "4"],
            ["501", "506", "508", "509", "502"]
        ]

    【匹配规则】
    1. 只在当前 flow1 时间范围内找周期。
    2. 多个周期模板按顺序尝试。
    3. 长模板优先匹配，避免短模板提前截断长模板。
    4. 找到一个周期后，直接跳过该周期长度，继续找下一个周期。

    【返回】
    [
        {
            "pattern": ["1", "2", "3", "4"],
            "items": [阶段1区间, 阶段2区间, 阶段3区间, 阶段4区间]
        },
        ...
    ]
    """

    useful = []

    for fallback_index, item in enumerate(intervals):
        if item["start"] < start_time or item["end"] > end_time:
            continue
        normalized = dict(item)
        normalized.setdefault("layer_index", fallback_index)
        normalized.setdefault("data_boundary_partial", False)
        useful.append(normalized)

    cycles = []
    i = 0

    while i < len(useful):
        matched = False

        for pattern in patterns:
            n = len(pattern)

            if i + n > len(useful):
                continue

            window = useful[i:i + n]
            stages = [str(x["stage"]) for x in window]

            if stages == pattern:
                if any(x["data_boundary_partial"] for x in window):
                    continue
                cycles.append({
                    "pattern": list(pattern),
                    "start": window[0]["start"],
                    "end": window[-1]["end"],
                    "start_layer_index": window[0]["layer_index"],
                    "end_layer_index": window[-1]["layer_index"],
                    "items": window,
                })

                i += n
                matched = True
                break

        if not matched:
            i += 1

    return cycles


def select_consistent_cycle_group(cycles, target_start=None, target_end=None):
    """Select one stable same-template run for a 10-minute training window."""
    pattern_groups = group_consecutive_same_pattern_cycles(cycles)
    structural_groups = [
        group
        for group in pattern_groups
        if len(group) >= MIN_CONSECUTIVE_CYCLES
    ]
    consistent_groups = []
    change_breaks = []
    for group in structural_groups:
        segments, group_breaks = split_cycle_group_on_stage_change(
            group,
            max_change_seconds=MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        )
        change_breaks.extend(group_breaks)
        consistent_groups.extend(
            segment
            for segment in segments
            if len(segment) >= MIN_CONSECUTIVE_CYCLES
        )

    selected_group = None
    if consistent_groups:
        if target_start is None or target_end is None:
            selected_group = min(
                consistent_groups,
                key=lambda group: (-len(group), int(group[0]["start"])),
            )
        else:
            target_twice_midpoint = int(target_start) + int(target_end)

            def group_key(group):
                distances = []
                for index in range(
                    len(group) - MIN_CONSECUTIVE_CYCLES + 1
                ):
                    subset = group[index:index + MIN_CONSECUTIVE_CYCLES]
                    subset_twice_midpoint = int(subset[0]["start"]) + int(
                        subset[-1]["end"]
                    )
                    distances.append(abs(
                        subset_twice_midpoint - target_twice_midpoint
                    ))
                return min(distances), -len(group), int(group[0]["start"])

            selected_group = min(consistent_groups, key=group_key)

    selected_count = len(selected_group or [])
    audit = {
        "complete_cycle_count": len(cycles),
        "complete_pattern_counts": dict(Counter(
            "-".join(cycle["pattern"])
            for cycle in cycles
        )),
        "consecutive_pattern_group_sizes": [
            len(group) for group in pattern_groups
        ],
        "structural_group_count": len(structural_groups),
        "consistent_group_count": len(consistent_groups),
        "stage_change_limit_seconds": MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        "stage_change_break_count": len(change_breaks),
        "stage_change_breaks": change_breaks,
        "selected_cycle_count": selected_count,
        "rejected_cycle_count": len(cycles) - selected_count,
        "selected_pattern": (
            list(selected_group[0]["pattern"])
            if selected_group
            else None
        ),
        "selected_group_start": (
            int(selected_group[0]["start"])
            if selected_group
            else None
        ),
        "selected_group_end": (
            int(selected_group[-1]["end"])
            if selected_group
            else None
        ),
    }
    return selected_group or [], audit


def select_nearest_three_cycles(cycles, window_start, window_end):
    if len(cycles) <= MIN_CONSECUTIVE_CYCLES:
        return list(cycles)

    target_twice_midpoint = int(window_start) + int(window_end)
    candidates = []
    for index in range(len(cycles) - MIN_CONSECUTIVE_CYCLES + 1):
        subset = cycles[index:index + MIN_CONSECUTIVE_CYCLES]
        subset_twice_midpoint = int(subset[0]["start"]) + int(
            subset[-1]["end"]
        )
        candidates.append((
            abs(subset_twice_midpoint - target_twice_midpoint),
            int(subset[0]["start"]),
            subset,
        ))
    return list(min(candidates, key=lambda item: (item[0], item[1]))[2])


def calc_direction_time_from_cycles(cycles, road_id, lines3):
    """
    【函数作用】
    根据窗口内全部完整周期的阶段区间，统计各方向累计放行时间。

    【cycles 结构】
    [
        {
            "pattern": ["1", "2", "3", "4"],
            "items": [阶段1区间, 阶段2区间, 阶段3区间, 阶段4区间]
        }
    ]

    【返回】
    {
        "U": 秒数,
        "D": 秒数,
        "L": 秒数,
        "R": 秒数,
        "UTL": 秒数,
        "DTL": 秒数,
        "LTL": 秒数,
        "RTL": 秒数
    }
    """

    result = {
        "U": 0,
        "D": 0,
        "L": 0,
        "R": 0,
        "UTL": 0,
        "DTL": 0,
        "LTL": 0,
        "RTL": 0,
    }

    for cycle in cycles:
        for item in cycle["items"]:
            stage = str(item["stage"])
            duration = item["duration"]

            phase_name = lines3[road_id]["phase"].get(stage)

            if phase_name not in PHASE_DIRECTION_MAP:
                continue

            for direction in PHASE_DIRECTION_MAP[phase_name]:
                result[direction] += duration

    return result


def supported_dedicated_left_directions(road_id, cross_info):
    """Return TL directions backed by a 1A lane and an active cycle phase."""
    cross_config = cross_info.get(str(road_id), {})
    lane_maps = cross_config.get("LaneNo", {})
    active_stages = {
        str(stage)
        for pattern in cross_config.get("Cycle", [])
        if isinstance(pattern, list)
        for stage in pattern
    }
    released_directions = set()
    phase_config = cross_config.get("phase", {})
    for stage in active_stages:
        phase_name = phase_config.get(stage, "")
        released_directions.update(
            PHASE_DIRECTION_MAP.get(str(phase_name).strip().upper(), ())
        )

    supported = set()
    for direction in BASE_FLOW_DIRECTIONS:
        lane_types = lane_maps.get(direction, {}).values()
        has_dedicated_left_lane = any(
            is_dedicated_left(lane_type)
            for lane_type in lane_types
        )
        left_direction = direction + "TL"
        if has_dedicated_left_lane and left_direction in released_directions:
            supported.add(left_direction)
    return supported


# ============================================================
# 核心加工函数
# ============================================================

def split_flow_by_movement(flow, road_id, cross_info):
    """Split each vehicle into either a base or dedicated-left flow vector."""
    flow_vectors = {
        direction: [0] * 10
        for direction in (
            "U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL"
        )
    }
    stats = Counter(input_records=len(flow))
    cross_config = cross_info.get(str(road_id), {})
    detector_map = cross_config.get("jtll_ddbh", {})
    lane_maps = cross_config.get("LaneNo", {})

    for record in flow:
        detector_id = str(record.get("jtll_ddbh", ""))
        direction = detector_map.get(detector_id)
        if direction not in BASE_FLOW_DIRECTIONS:
            stats["skipped_missing_direction"] += 1
            continue

        try:
            lane = int(record["lan"])
        except (KeyError, TypeError, ValueError):
            stats["skipped_invalid_lane"] += 1
            continue

        if not 0 <= lane < 10:
            stats["skipped_invalid_lane"] += 1
            continue

        lane_type = str(
            lane_maps.get(direction, {}).get(str(lane), "")
        ).strip().upper()
        if not lane_type:
            stats["skipped_unconfigured_lane"] += 1
            continue

        target_direction = capacity_experience_direction(direction, lane_type)
        if target_direction is None:
            policy = classify_lane_type(lane_type)
            stats["excluded_non_capacity_records"] += 1
            stats[
                f"excluded_lane_type_{policy['lane_type'] or 'empty'}"
            ] += 1
            if policy["control"] == "uncontrolled":
                stats["excluded_uncontrolled_records"] += 1
            else:
                stats["excluded_unverified_records"] += 1
            continue

        if target_direction.endswith("TL"):
            stats["left_turn_records"] += 1
        else:
            stats["base_direction_records"] += 1

        flow_vectors[target_direction][lane] += 1

    stats["accepted_records"] = (
        stats["base_direction_records"] + stats["left_turn_records"]
    )
    return flow_vectors, dict(stats)

def jiagong(
    flow,
    phase_intervals,
    road_id,
    diyici,
    window_start=None,
    window_end=None,
    excluded_directions=None,
):
    """
    【函数作用】
    处理一段 flow1 数据，生成经验表。

    【业务口径】
    1. flow 是约 10min 的流量数据。
       车流统计整个 flow，用于表示 10min 通行能力。

    2. 相位时间只使用固定 10 分钟窗口内同模板连续且稳定的一组周期，
       周期模板从 cross_info.json 的 Cycle 字段读取，至少需要 3 个周期。

    3. 三周期时间来自阶段区间 duration，
       不再用逐秒 Cycle 判断。

    4. 周期质量门禁：
       不同模板不能混合；相邻周期同一阶段变化超过 8 秒时断组，
       断组后不足 3 个周期则不计入经验表。
    """

    if not flow:
        return {"status": "empty_flow"}

    excluded_directions = {
        str(direction).upper()
        for direction in (excluded_directions or [])
        if str(direction).upper() in BASE_FLOW_DIRECTIONS
    }

    patterns = get_cycle_patterns_from_cross_info(road_id)

    if not patterns:
        print(f"未配置周期阶段顺序 Cycle: road_id={road_id}")
        return {"status": "missing_cycle_config"}

    kaishi_time = (
        int(window_start)
        if window_start is not None
        else get_time_sec(flow[0]["time"])
    )
    jieshu_time = (
        int(window_end)
        if window_end is not None
        else get_time_sec(flow[-1]["time"])
    )

    # ============================================================
    # 1. 按 cross_info.json 中的 Cycle 周期模板抽取窗口内全部完整周期
    # ============================================================

    cycles = find_complete_cycles_from_intervals(
        intervals=phase_intervals,
        patterns=patterns,
        start_time=kaishi_time,
        end_time=jieshu_time
    )

    initial_complete_cycle_count = len(cycles)
    observation_start = kaishi_time
    observation_end = jieshu_time
    observation_expansion_attempted = False
    expansion_decision = cycle_observation_expansion_decision(cycles)

    # Flow remains fixed to 10 minutes. Phase observation grows to 15
    # minutes only when the initial complete cycles have a median over 200s.
    if expansion_decision["should_expand"]:
        observation_start, observation_end = centered_observation_bounds(
            kaishi_time,
            jieshu_time,
        )
        observation_expansion_attempted = True
        cycles = find_complete_cycles_from_intervals(
            intervals=phase_intervals,
            patterns=patterns,
            start_time=observation_start,
            end_time=observation_end,
        )

    cycle_observation = {
        "flow_window_start": kaishi_time,
        "flow_window_end": jieshu_time,
        "flow_window_seconds": jieshu_time - kaishi_time + 1,
        "initial_complete_cycle_count": initial_complete_cycle_count,
        "cycle_observation_start": observation_start,
        "cycle_observation_end": observation_end,
        "cycle_observation_seconds": observation_end - observation_start + 1,
        "expansion_attempted": observation_expansion_attempted,
        "expanded": observation_expansion_attempted,
        "expansion_decision": expansion_decision,
    }

    if len(cycles) < MIN_CONSECUTIVE_CYCLES:
        debug_print(
            f"未找到3个完整周期: road_id={road_id}, "
            f"diyici={diyici}, cycles={len(cycles)}, "
            f"time={fmt_time(kaishi_time)}~{fmt_time(jieshu_time)}"
        )
        debug_print(f"已配置周期模板: {patterns}")
        return {
            "status": "fewer_than_three_cycles",
            "cycles": len(cycles),
            "complete_cycles_found": len(cycles),
            "rejected_cycles": 0,
            "cycle_observation": cycle_observation,
        }

    selected_cycles, cycle_gate = select_consistent_cycle_group(
        cycles,
        target_start=kaishi_time,
        target_end=jieshu_time,
    )
    cycle_gate = dict(cycle_gate)
    cycle_gate.update(cycle_observation)
    if not selected_cycles:
        return {
            "status": "no_consistent_same_pattern_cycle_group",
            "cycles": len(cycles),
            "complete_cycles_found": len(cycles),
            "rejected_cycles": len(cycles),
            "cycle_gate": cycle_gate,
            "cycle_observation": cycle_observation,
        }
    selected_cycles = select_nearest_three_cycles(
        selected_cycles,
        kaishi_time,
        jieshu_time,
    )
    cycle_gate["selected_cycle_count"] = len(selected_cycles)
    cycle_gate["rejected_cycle_count"] = len(cycles) - len(selected_cycles)
    cycle_gate["selected_group_start"] = int(selected_cycles[0]["start"])
    cycle_gate["selected_group_end"] = int(selected_cycles[-1]["end"])
    cycles = selected_cycles

    rejected_cycle_count = int(cycle_gate["rejected_cycle_count"])

    # ============================================================
    # 2. 根据 3 个周期的阶段 duration 计算方向累计时间
    # ============================================================

    direction_time = calc_direction_time_from_cycles(
        cycles=cycles,
        road_id=road_id,
        lines3=lines3
    )

    U = direction_time["U"]
    D = direction_time["D"]
    L = direction_time["L"]
    R = direction_time["R"]
    UTL = direction_time["UTL"]
    DTL = direction_time["DTL"]
    LTL = direction_time["LTL"]
    RTL = direction_time["RTL"]

    debug_print("=" * 100)
    debug_print(f"road_id={road_id}, diyici={diyici}")
    debug_print(f"flow时间: {fmt_time(kaishi_time)} ~ {fmt_time(jieshu_time)}")

    debug_print("抽取的完整周期:")
    for idx, cycle in enumerate(cycles, start=1):
        debug_print(f"周期{idx} 模板={cycle['pattern']}:")

        for x in cycle["items"]:
            debug_print(
                f"    阶段{x['stage']} "
                f"{fmt_time(x['start'])}~{fmt_time(x['end'])} "
                f"{x['duration']}s"
            )

    debug_print(
        "三周期累计时间:",
        {
            "U": U,
            "D": D,
            "L": L,
            "R": R,
            "UTL": UTL,
            "DTL": DTL,
            "LTL": LTL,
            "RTL": RTL,
        }
    )

    # ============================================================
    # 3. 统计整个 flow1 的 10min 通行能力
    # ============================================================

    liuliang, flow_split_stats = split_flow_by_movement(
        flow=flow,
        road_id=road_id,
        cross_info=lines3,
    )
    debug_print("直行/左转流量拆分:", flow_split_stats)

    # ============================================================
    # 4. 生成经验表
    # ============================================================

    cycle_count = len(cycles)
    if road_id != "1700275":
        zhongbiao = {
            "U": {
                int(round(U / cycle_count)): liuliang["U"]
            },
            "D": {
                int(round(D / cycle_count)): liuliang["D"]
            },
            "L": {
                int(round(L / cycle_count)): liuliang["L"]
            },
            "R": {
                int(round(R / cycle_count)): liuliang["R"]
            },
            "RTL": {
                int(round(RTL / cycle_count)): liuliang["RTL"]
            },
            "LTL": {
                int(round(LTL / cycle_count)): liuliang["LTL"]
            },
            "UTL": {
                int(round(UTL / cycle_count)): liuliang["UTL"]
            },
            "DTL": {
                int(round(DTL / cycle_count)): liuliang["DTL"]
            },
        }
    else:
        zhongbiao = {
            "U": {
                U // 6: liuliang["U"]
            },
            "D": {
                D // 6: liuliang["D"]
            },
            "L": {
                L // 6: liuliang["L"]
            },
            "R": {
                R // 6: liuliang["R"]
            },
            "RTL": {
                RTL // 6: liuliang["RTL"]
            },
            "LTL": {
                LTL // 6: liuliang["LTL"]
            },
            "UTL": {
                UTL // 6: liuliang["UTL"]
            },
            "DTL": {
                DTL // 6: liuliang["DTL"]
            },
        }

    for direction in excluded_directions:
        zhongbiao.pop(direction, None)
        zhongbiao.pop(direction + "TL", None)

    supported_left_directions = supported_dedicated_left_directions(
        road_id,
        lines3,
    )
    excluded_left_directions = sorted(
        {direction + "TL" for direction in BASE_FLOW_DIRECTIONS}
        - supported_left_directions
    )
    for direction in excluded_left_directions:
        zhongbiao.pop(direction, None)

    # ============================================================
    # 5. 过滤异常小时间
    # ============================================================

    for d, key in zhongbiao.items():
        for time1, shuzu in key.items():
            if int(time1) <= 10 and sum(shuzu) != 0:
                zhongbiao[d][time1] = [0] * 10

    debug_print("zhongbiao:")
    debug_print(zhongbiao)

    # ============================================================
    # 6. 返回当前窗口经验；主流程负责内存合并和分日原子保存
    # ============================================================
    return {
        "status": "accepted",
        "cycles": len(cycles),
        "complete_cycles_found": int(cycle_gate["complete_cycle_count"]),
        "rejected_cycles": rejected_cycle_count,
        "cycle_gate": cycle_gate,
        "cycle_observation": cycle_observation,
        "cycle_metadata": {
            "valid_cycle_count": len(cycles),
            "rejected_cycle_count": rejected_cycle_count,
            "cycle_gate": cycle_gate,
            "cycle_observation": cycle_observation,
            "pattern_counts": dict(
                Counter(
                    "-".join(cycle["pattern"])
                    for cycle in cycles
                )
            ),
            "cycle_durations": [
                sum(int(item["duration"]) for item in cycle["items"])
                for cycle in cycles
            ],
        },
        "flow_records": len(flow),
        "flow_split": flow_split_stats,
        "excluded_directions": sorted(excluded_directions),
        "excluded_left_turn_directions": excluded_left_directions,
        "experience": zhongbiao,
    }


# ============================================================
# 主流程
# ============================================================

def update_training_stats(stats, result):
    status = result.get("status", "unknown")
    stats["windows_seen"] += 1
    stats[status] += 1
    stats["cycles_seen"] += int(
        result.get("complete_cycles_found", result.get("cycles", 0))
    )
    stats["cycles_rejected"] += int(result.get("rejected_cycles", 0))
    stats["flow_records_used"] += int(result.get("flow_records", 0))
    cycle_observation = result.get("cycle_observation", {})
    expansion_attempted = bool(cycle_observation.get("expansion_attempted"))
    stats["expanded_cycle_observation_attempts"] += int(expansion_attempted)
    expansion_reason = cycle_observation.get("expansion_decision", {}).get(
        "reason"
    )
    if expansion_reason:
        stats[f"cycle_observation_decision_{expansion_reason}"] += 1
    cycle_gate = result.get("cycle_gate", {})
    stats["cycle_pattern_groups_seen"] += int(
        len(cycle_gate.get("consecutive_pattern_group_sizes", []))
    )
    stats["cycle_structural_groups_seen"] += int(
        cycle_gate.get("structural_group_count", 0)
    )
    stats["cycle_consistent_groups_seen"] += int(
        cycle_gate.get("consistent_group_count", 0)
    )
    stats["cycle_stage_change_breaks"] += int(
        cycle_gate.get("stage_change_break_count", 0)
    )

    if status != "accepted":
        stats["expanded_cycle_observation_rejected"] += int(
            expansion_attempted
        )
        return

    stats["expanded_cycle_observation_accepted"] += int(expansion_attempted)
    stats["cycles_used"] += int(result.get("cycles", 0))
    flow_split = result.get("flow_split", {})
    stats["base_direction_flow_records"] += int(
        flow_split.get("base_direction_records", 0)
    )
    stats["left_turn_flow_records"] += int(
        flow_split.get("left_turn_records", 0)
    )
    stats["classified_flow_records"] += int(
        flow_split.get("accepted_records", 0)
    )
    for direction in result.get("excluded_directions", []):
        stats[f"excluded_direction_{direction}_accepted_windows"] += 1
    for direction in result.get("excluded_left_turn_directions", []):
        stats[f"excluded_direction_{direction}_accepted_windows"] += 1


def training_stats_report(stats):
    result = dict(stats)
    windows_seen = int(result.get("windows_seen", 0))
    accepted = int(result.get("accepted", 0))
    result["acceptance_rate"] = (
        round(accepted / windows_seen, 6) if windows_seen else 0.0
    )
    return result


def run_training():
    started_at = time.perf_counter()
    os.makedirs(os.path.dirname(os.path.abspath(JIYAN_PATH)), exist_ok=True)

    reset_output = os.environ.get("AITC_RESET_OUTPUT") == "1"
    if reset_output or not os.path.exists(JIYAN_PATH):
        experience_data = {}
    else:
        experience_data = load_result(JIYAN_PATH)
        if not isinstance(experience_data, dict):
            raise ValueError(f"经验表顶层必须是对象: {JIYAN_PATH}")

    road_ids = sorted(shipin_roid)
    if not road_ids:
        raise ValueError("至少需要配置一个训练路口")
    unknown_road_ids = sorted(set(road_ids) - set(lines3))
    if unknown_road_ids:
        raise ValueError(f"cross_info.json 中不存在训练路口: {unknown_road_ids}")

    training_stats = {road_id: Counter() for road_id in road_ids}
    daily_training_stats = {}
    candidate_audit = ExperienceCandidateAudit(
        low_support_threshold=os.environ.get(
            "AITC_AUDIT_LOW_SUPPORT_THRESHOLD",
            "3",
        ),
        dominant_max_ratio=os.environ.get(
            "AITC_AUDIT_DOMINANT_MAX_RATIO",
            "1.5",
        ),
        dominant_max_min_gap=os.environ.get(
            "AITC_AUDIT_DOMINANT_MAX_MIN_GAP",
            "5",
        ),
        min_date_support=os.environ.get(
            "AITC_AUDIT_MIN_DATE_SUPPORT",
            "2",
        ),
        iqr_outlier_multiplier=os.environ.get(
            "AITC_AUDIT_IQR_OUTLIER_MULTIPLIER",
            "1.5",
        ),
    )
    candidate_audit_path = (
        os.path.splitext(JIYAN_PATH)[0] + "_candidate_audit.json"
    )
    candidate_samples_path = (
        os.path.splitext(JIYAN_PATH)[0] + "_candidate_samples.json"
    )

    def save_candidate_outputs():
        report = candidate_audit.build_report()
        report["dates"] = list(daily_training_stats)
        report["road_ids"] = road_ids
        write_json_atomic(candidate_audit_path, report)
        samples = candidate_audit.build_samples()
        samples["dates"] = list(daily_training_stats)
        samples["road_ids"] = road_ids
        write_json_atomic(candidate_samples_path, samples)
        return report

    quality_report_dir = os.environ.get(
        "AITC_QUALITY_REPORT_DIR",
        os.path.join(PROJECT_ROOT, "logs_data", "quality_reports"),
    )

    for data_day in datas:
        flow_path = os.path.join(
            PROJECT_ROOT,
            "logs_data",
            "flow",
            f"{data_day}_flow.txt",
        )
        extend_path = os.path.join(
            PROJECT_ROOT,
            "logs_data",
            "extend",
            f"{data_day}_extend.txt",
        )
        quality_report_path = os.path.join(
            quality_report_dir,
            f"{data_day}_quality_report.json",
        )
        flow, extend, quality_report = clean_training_inputs(
            flow_path=flow_path,
            extend_path=extend_path,
            cross_info=lines3,
            target_cross_ids=shipin_roid,
            max_stage_gap_seconds=DEFAULT_MAX_STAGE_GAP_SECONDS,
            report_path=quality_report_path,
        )
        print(f"数据清洗完成，质量报告: {quality_report_path}")
        debug_print(f"清洗汇总: {quality_report['totals']}")

        day_stats = {road_id: Counter() for road_id in road_ids}
        daily_training_stats[data_day] = day_stats

        for road_id in road_ids:
            road_extend = extend.get(road_id, {})
            road_flow = flow.get(road_id, [])
            flow_coverage = quality_report.get("crosses", {}).get(
                road_id,
                {},
            ).get("flow_coverage", {})
            excluded_directions = (
                flow_coverage.get("unavailable_directions", [])
                if FILTER_UNAVAILABLE_DIRECTIONS
                else []
            )

            if not road_extend:
                print(f"路口缺少阶段数据: road_id={road_id}")
                training_stats[road_id]["missing_stage_data"] += 1
                day_stats[road_id]["missing_stage_data"] += 1
                continue

            if not road_flow:
                print(f"路口缺少流量数据: road_id={road_id}")
                training_stats[road_id]["missing_flow_data"] += 1
                day_stats[road_id]["missing_flow_data"] += 1
                continue

            # 清洗器沿用上一阶段补齐不超过3秒的采集缺口。
            # 阶段可以直接切换；更长的无记录区间保留为未知分层。
            phase_intervals = compress_phase_intervals(road_extend)

            windows = {}
            for row in road_flow:
                row_time = get_time_sec(row["time"])
                window_start = (row_time // WINDOW_SECONDS) * WINDOW_SECONDS
                windows.setdefault(window_start, []).append(row)

            for window_index, window_start in enumerate(sorted(windows), start=1):
                result = jiagong(
                    flow=windows[window_start],
                    phase_intervals=phase_intervals,
                    road_id=road_id,
                    diyici=window_index,
                    window_start=window_start,
                    window_end=window_start + WINDOW_SECONDS - 1,
                    excluded_directions=excluded_directions,
                )
                update_training_stats(training_stats[road_id], result)
                update_training_stats(day_stats[road_id], result)

                if result.get("status") != "accepted":
                    continue

                candidate_audit.add_experience(
                    road_id,
                    result["experience"],
                    data_day=data_day,
                    window_start=window_start,
                    metadata=result.get("cycle_metadata", {}),
                )
                previous = experience_data.get(road_id, {})
                experience_data[road_id] = merge_zhongbiao(
                    previous,
                    result["experience"],
                    road_id,
                )

        # 每个训练日结束后保存一次，避免逐窗口重写整张经验表。
        experience_data = save_experience_table(experience_data)
        save_candidate_outputs()
        day_summary = {
            road_id: training_stats_report(stats)
            for road_id, stats in sorted(day_stats.items())
        }
        print(f"日期训练完成: {data_day}, 统计={day_summary}")

    candidate_audit_report = save_candidate_outputs()
    training_report_path = os.path.splitext(JIYAN_PATH)[0] + "_training_report.json"
    training_report = {
        "dates": datas,
        "road_ids": road_ids,
        "output": os.path.abspath(JIYAN_PATH),
        "candidate_audit_output": os.path.abspath(candidate_audit_path),
        "candidate_samples_output": os.path.abspath(candidate_samples_path),
        "candidate_audit_summary": {
            road_id: road_report.get("summary", {})
            for road_id, road_report in candidate_audit_report.get(
                "roads",
                {},
            ).items()
        },
        "window_seconds": WINDOW_SECONDS,
        "cycle_observation_window_seconds": (
            CYCLE_OBSERVATION_WINDOW_SECONDS
        ),
        "adaptive_cycle_observation_enabled": True,
        "long_cycle_threshold_seconds": LONG_CYCLE_THRESHOLD_SECONDS,
        "long_cycle_duration_statistic": "median_of_initial_complete_cycles",
        "minimum_valid_cycles": MIN_CONSECUTIVE_CYCLES,
        "same_template_cycles_required": True,
        "max_adjacent_stage_change_seconds": (
            MAX_ADJACENT_STAGE_CHANGE_SECONDS
        ),
        "legacy_fixed_minimum_stage_duration_enabled": False,
        "data_boundary_partial_layers_rejected": True,
        "verbose_logging": TRAIN_VERBOSE,
        "filter_unavailable_directions": FILTER_UNAVAILABLE_DIRECTIONS,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "roads": {
            road_id: training_stats_report(stats)
            for road_id, stats in sorted(training_stats.items())
        },
        "days": {
            data_day: {
                road_id: training_stats_report(stats)
                for road_id, stats in sorted(day_stats.items())
            }
            for data_day, day_stats in daily_training_stats.items()
        },
    }
    write_json_atomic(training_report_path, training_report)
    print(f"训练统计报告: {training_report_path}")
    print(f"候选样本审计报告: {candidate_audit_path}")
    print(f"候选样本明细: {candidate_samples_path}")
    return experience_data, training_report


if __name__ == "__main__":
    run_training()
