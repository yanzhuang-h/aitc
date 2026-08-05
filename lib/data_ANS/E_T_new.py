import json
import time
import os
from datetime import datetime, timedelta


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.abspath(os.path.join(BASE_DIR, os.pardir))
PROJECT_ROOT = os.path.abspath(os.path.join(LIB_DIR, os.pardir))
JIYAN_PATH = os.path.join(LIB_DIR, "lin_shi_111.json")
INFO_PATH = os.path.join(LIB_DIR, "cross_info.json")


with open(INFO_PATH, "r", encoding="utf-8") as f:
    lines3 = json.load(f)


# ============================================================
# 配置区
# ============================================================
datas = [
# '2026-04-23',
# '2026-04-22',
# '2026-04-21',
# '2026-04-20',
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
#
# '2026-03-04',


         #
         # '2026-02-03','2026-02-04',
    (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')]
# datas = [
#     "2026-04-23",
#     # "2026-04-22",
#     # "2026-04-21",
# ]

shipin_roid = {
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

# 【异常检测阈值】
# 任意阶段执行时间 <= 15s，则认为当前抽取的三周期异常，不计入经验表。
ABNORMAL_STAGE_DURATION_THRESHOLD = 15


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

    with open(JIYAN_PATH, "w", encoding="utf-8") as f:
        json.dump(data_old, f, ensure_ascii=False, indent=2)


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
                sorted_data[cross_id][direction][time_key] = time_dict[time_key]

    return sorted_data


def sort_zhong():
    """
    【函数作用】
    对 lin_shi.json 里的时间 key 排序。
    """
    save_path = JIYAN_PATH
    result_data = load_result(save_path)
    sorted_result = sort_by_time(result_data)

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(sorted_result, f, indent=2, ensure_ascii=False)

    print("排序完成已保存")


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
    从 cross_info.json 中读取指定路口的 zhouqi 周期配置。

    【cross_info.json 格式示例】
    "zhouqi": [
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

    zhouqi = lines3[road_id].get("zhouqi", [])

    if not zhouqi:
        print(f"cross_info.json 中该路口未配置 zhouqi: road_id={road_id}")
        return []

    patterns = []

    for pattern in zhouqi:
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

        if stage == cur_stage:
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

    return intervals


def find_three_complete_cycles_from_intervals(intervals, patterns, start_time, end_time):
    """
    【函数作用】
    从阶段区间中，按 cross_info.json 中配置的多个 zhouqi 模板，
    抽取 3 个完整周期。

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

    for item in intervals:
        if item["end"] < start_time:
            continue
        if item["start"] > end_time:
            continue

        useful.append(item)

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
                cycles.append({
                    "pattern": pattern,
                    "items": window
                })

                i += n
                matched = True
                break

        if len(cycles) == 3:
            break

        if not matched:
            i += 1

    return cycles


def check_cycles_has_abnormal_stage(cycles, threshold=15):
    """
    【函数作用】
    检查抽取到的 3 个完整周期里，是否存在异常阶段。

    【异常规则】
    任意一个阶段的执行时间 <= threshold 秒，
    则认为这组三周期异常。

    【返回】
    has_abnormal:
        True  表示存在异常阶段
        False 表示没有异常阶段

    abnormal_list:
        异常阶段列表，方便打印排查。
    """
    abnormal_list = []

    for cycle_idx, cycle in enumerate(cycles, start=1):
        pattern = cycle.get("pattern", [])

        for item in cycle.get("items", []):
            duration = int(item["duration"])

            if duration <= threshold:
                abnormal_list.append({
                    "cycle_idx": cycle_idx,
                    "pattern": pattern,
                    "stage": str(item["stage"]),
                    "start": item["start"],
                    "end": item["end"],
                    "duration": duration
                })

    return len(abnormal_list) > 0, abnormal_list


def calc_direction_time_from_cycles(cycles, road_id, lines3):
    """
    【函数作用】
    根据 3 个完整周期的阶段区间，统计各方向累计放行时间。

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

    yingshe_1 = {
        "UD": ["U", "D"],
        "LR": ["L", "R"],
        "UDL": ["UTL", "DTL"],
        "LRL": ["LTL", "RTL"],
        "U": ["U", "UTL"],
        "D": ["D", "DTL"],
        "L": ["L", "LTL"],
        "R": ["R", "RTL"],
        "LTD": ["LTL", "D"],
    }

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

            if phase_name not in yingshe_1:
                continue

            for direction in yingshe_1[phase_name]:
                result[direction] += duration

    return result


# ============================================================
# 核心加工函数
# ============================================================

def jiagong(flow, phase_intervals, road_id, diyici):
    """
    【函数作用】
    处理一段 flow1 数据，生成经验表。

    【业务口径】
    1. flow 是约 10min 的流量数据。
       车流统计整个 flow，用于表示 10min 通行能力。

    2. 相位时间从这个 flow 时间段中抽取 3 个完整周期。
       周期模板从 cross_info.json 的 zhouqi 字段读取。

    3. 三周期时间来自阶段区间 duration，
       不再用逐秒 zhouqi 判断。

    4. 异常检测：
       如果抽取到的 3 个周期里，任意阶段持续时间 <= 15s，
       则认为这组三周期异常，不计入经验表。
    """

    if not flow:
        return

    patterns = get_cycle_patterns_from_cross_info(road_id)

    if not patterns:
        print(f"未配置周期阶段顺序 zhouqi: road_id={road_id}")
        return

    kaishi_time = get_time_sec(flow[0]["time"])
    jieshu_time = get_time_sec(flow[-1]["time"])

    # ============================================================
    # 1. 按 cross_info.json 中的 zhouqi 周期模板抽取 3 个完整周期
    # ============================================================

    cycles = find_three_complete_cycles_from_intervals(
        intervals=phase_intervals,
        patterns=patterns,
        start_time=kaishi_time,
        end_time=jieshu_time
    )

    if len(cycles) < 3:
        print(
            f"未找到3个完整周期: road_id={road_id}, "
            f"diyici={diyici}, cycles={len(cycles)}, "
            f"time={fmt_time(kaishi_time)}~{fmt_time(jieshu_time)}"
        )
        print(f"已配置周期模板: {patterns}")
        return

    # ============================================================
    # 1.1 三周期异常检测
    #
    # 只要这 3 个周期中存在任意一个阶段 duration <= 15s，
    # 就认为这组三周期异常，不计入经验表。
    # ============================================================

    has_abnormal, abnormal_list = check_cycles_has_abnormal_stage(
        cycles=cycles,
        threshold=ABNORMAL_STAGE_DURATION_THRESHOLD
    )

    if has_abnormal:
        print("=" * 100)
        print(
            f"三周期存在异常阶段，不计入经验表: road_id={road_id}, "
            f"diyici={diyici}, "
            f"flow时间={fmt_time(kaishi_time)}~{fmt_time(jieshu_time)}"
        )

        for item in abnormal_list:
            print(
                f"    异常周期={item['cycle_idx']}  "
                f"模板={item['pattern']}  "
                f"阶段={item['stage']}  "
                f"阶段时间={fmt_time(item['start'])}~{fmt_time(item['end'])}  "
                f"持续={item['duration']}s  "
                f"阈值<={ABNORMAL_STAGE_DURATION_THRESHOLD}s"
            )

        return

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

    print("=" * 100)
    print(f"road_id={road_id}, diyici={diyici}")
    print(f"flow时间: {fmt_time(kaishi_time)} ~ {fmt_time(jieshu_time)}")

    print("抽取的3个周期:")
    for idx, cycle in enumerate(cycles, start=1):
        print(f"周期{idx} 模板={cycle['pattern']}:")

        for x in cycle["items"]:
            print(
                f"    阶段{x['stage']} "
                f"{fmt_time(x['start'])}~{fmt_time(x['end'])} "
                f"{x['duration']}s"
            )

    print(
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

    liuliang = {
        "L": [0] * 10,
        "R": [0] * 10,
        "U": [0] * 10,
        "D": [0] * 10,
        "UTL": [0] * 10,
        "DTL": [0] * 10,
        "LTL": [0] * 10,
        "RTL": [0] * 10,
    }

    phase_duration = {
        "L": L,
        "R": R,
        "U": U,
        "D": D,
        "UTL": UTL,
        "DTL": DTL,
        "LTL": LTL,
        "RTL": RTL,
    }

    for x in flow:
        if x["jtll_ddbh"] not in lines3[road_id]["jtll_ddbh"]:
            print("缺失方向符号", x["jtll_ddbh"], road_id)
            continue

        direction = lines3[road_id]["jtll_ddbh"][x["jtll_ddbh"]]
        lane = int(x["lan"])

        if 0 <= lane < 10:
            liuliang[direction][lane] += 1

        # 如果某个左转方向有放行时间，则用对应主方向流量补左转流量
        for d in "UDLR":
            xin = d + "TL"

            if phase_duration[xin] > 0:
                for lan in range(10):
                    liuliang[xin][lan] = liuliang[d][lan]

    # ============================================================
    # 4. 生成经验表
    # ============================================================

    if road_id != "1700275":
        zhongbiao = {
            "U": {
                U // 3: liuliang["U"]
            },
            "D": {
                D // 3: liuliang["D"]
            },
            "L": {
                L // 3: liuliang["L"]
            },
            "R": {
                R // 3: liuliang["R"]
            },
            "RTL": {
                RTL // 3: liuliang["RTL"]
            },
            "LTL": {
                LTL // 3: liuliang["LTL"]
            },
            "UTL": {
                UTL // 3: liuliang["UTL"]
            },
            "DTL": {
                DTL // 3: liuliang["DTL"]
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

    # ============================================================
    # 5. 过滤异常小时间
    # ============================================================

    for d, key in zhongbiao.items():
        for time1, shuzu in key.items():
            if int(time1) <= 10 and sum(shuzu) != 0:
                zhongbiao[d][time1] = [0] * 10

    print("zhongbiao:")
    print(zhongbiao)

    # ============================================================
    # 6. 保存经验表
    # ============================================================

    lao = load_json(road_id)
    data = merge_zhongbiao(lao, zhongbiao, road_id)
    save_json(data, road_id)


# ============================================================
# 主流程
# ============================================================

for data_day in datas:

    flow_path = os.path.join(PROJECT_ROOT, "logs_data", "flow", f"{data_day}_flow.txt")
    extend_path = os.path.join(PROJECT_ROOT, "logs_data", "extend", f"{data_day}_extend.txt")

    with open(flow_path, "r", encoding="utf-8") as f:
        lines1 = f.readlines()

    with open(extend_path, "r", encoding="utf-8") as f:
        lines2 = f.readlines()

    # ============================================================
    # 读取阶段数据 Extend_data
    # ============================================================

    extend = {}
    s1 = set()

    for line in lines2:
        try:
            data_json = json.loads(line)

            cross_id = str(data_json["CrossId"])
            s1.add(cross_id)

            if cross_id not in extend:
                extend[cross_id] = []

            ts = get_time_sec(data_json["time"])
            cur_stage_no = str(data_json["curStageNo"])

            extend[cross_id].append({
                ts: cur_stage_no
            })

        except Exception:
            continue

    print(s1)

    # ============================================================
    # 读取流量数据 Flow_data
    # ============================================================

    flow = {}

    for line in lines1:
        try:
            data_json = json.loads(line)

            cord_id = ""

            for cross_id in lines3:
                if data_json["jtll_ddbh"] in lines3[cross_id]["jtll_ddbh"]:
                    cord_id = cross_id
                    break

            if cord_id == "":
                continue

            if cord_id not in flow:
                flow[cord_id] = []

            xuyao = {
                "CrossId": cord_id,
                "time": data_json["ts"],
                "jtll_ddbh": data_json["jtll_ddbh"],
                "lan": int(data_json["ycsb_cdbh"]),
                "ycsb_xsfx": data_json.get("ycsb_xsfx", "")
            }

            flow[cord_id].append(xuyao)

        except Exception:
            continue

    # 每个路口车辆按时间排序
    for road_id in flow:
        flow[road_id].sort(key=lambda x: get_time_sec(x["time"]))

    s2 = set()

    for x in shipin_roid:
        s2.add(x)

    print(s2)

    diyici = 0

    for road_id in s2:
        flow1 = []
        t = 0
        last = 0

        road_extend = extend.get(road_id, [])
        road_flow = flow.get(road_id, [])

        if not road_extend:
            print(f"路口缺少阶段数据: road_id={road_id}")
            continue

        if not road_flow:
            print(f"路口缺少流量数据: road_id={road_id}")
            continue

        # ========================================================
        # 构造 raw 阶段表
        # ========================================================

        dict_id_raw = {}

        for x in road_extend:
            for key, zhi in x.items():
                dict_id_raw[int(key)] = str(zhi)

        # ========================================================
        # -1 和缺失秒归并到上一个有效阶段
        # ========================================================

        dict_id_filled = build_continuous_phase_dict(dict_id_raw)

        # ========================================================
        # 压缩成阶段执行区间
        # ========================================================

        phase_intervals = compress_phase_intervals(dict_id_filled)

        # ========================================================
        # 按 flow 的时间间隔切段
        #
        # 超过 600 秒认为进入新的一段。
        # 每段 flow1 表示约 10min 的通行能力统计范围。
        # ========================================================

        for tiao in road_flow:
            tiao_time = get_time_sec(tiao["time"])

            if t == 0:
                t = 1
                last = tiao_time

            if last + 600 <= tiao_time:
                diyici += 1

                if flow1:
                    jiagong(
                        flow=flow1,
                        phase_intervals=phase_intervals,
                        road_id=road_id,
                        diyici=diyici
                    )

                flow1 = []
                last = tiao_time

            flow1.append(tiao)

        # ========================================================
        # 处理最后一段 flow1
        # ========================================================

        if flow1:
            diyici += 1

            jiagong(
                flow=flow1,
                phase_intervals=phase_intervals,
                road_id=road_id,
                diyici=diyici
            )

        sort_zhong()
