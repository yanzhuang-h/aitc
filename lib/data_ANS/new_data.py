import json
import math
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LIB_DIR = BASE_DIR.parent

# 固定输出的方向顺序
DIRECTIONS = ["U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL"]


def percentile_80(values):
    """
    取 80% 分位值（nearest-rank）。
    例如：
    [1,2,3,4,5,6,7,8,9,10] -> 8
    [1,1,1,1,5,6,7,8,9,10] -> 8
    """
    if not values:
        return 0

    values = sorted(values)
    n = len(values)

    # nearest-rank: rank = ceil(0.8 * n)
    rank = math.ceil(0.8 * n)
    index = max(0, rank - 1)

    return values[index]


def extract_flow_values(lane_records):
    """
    从某个车道的经验列表中提取“通车数”。

    输入示例：
    [
        {"36": {"stage": 1772067262, "end": 1772067328, "zongtime": 66}},
        {"45": {"stage": 1772068000, "end": 1772068100, "zongtime": 100}}
    ]

    输出：
    [36, 45]
    """
    result = []

    if not isinstance(lane_records, list):
        return result

    for item in lane_records:
        if isinstance(item, dict):
            for k in item.keys():
                try:
                    result.append(int(k))
                except (ValueError, TypeError):
                    pass
        elif isinstance(item, (int, float)):
            result.append(int(item))
        elif isinstance(item, str):
            try:
                result.append(int(item))
            except ValueError:
                pass

    return result


def sort_time_keys(time_keys):
    """
    按数字排序时间 key，避免 '100' 排在 '20' 前面
    """
    def key_func(x):
        try:
            return int(x)
        except (ValueError, TypeError):
            return float("inf")

    return sorted(time_keys, key=key_func)


def compress_one_duration(duration_data):
    """
    将某个通行时间下的车道经验压缩成数组：
    [lane0_p80, lane1_p80, lane2_p80, ..., lane9_p80]

    也就是：
    0号车道 -> 下标0
    1号车道 -> 下标1
    ...
    9号车道 -> 下标9
    """
    lane_result = [0] * 10

    for lane_str, lane_records in duration_data.items():
        try:
            lane_idx = int(lane_str)
        except (ValueError, TypeError):
            continue

        if 0 <= lane_idx <= 9:
            flow_values = extract_flow_values(lane_records)
            lane_result[lane_idx] = percentile_80(flow_values)

    return lane_result


def compress_chi_lan(data):
    """
    压缩整个 chi_lan.json
    输出结构：
    {
        "1300044": {
            "U": {
                "13": [0,36,45,45,18,27,0,0,0,0],
                ...
            },
            "D": {},
            ...
        }
    }

    注意：
    数组下标 = 车道号
    """
    new_data = {}

    for cross_id, cross_data in data.items():
        new_data[cross_id] = {}

        for direction in DIRECTIONS:
            dir_data = cross_data.get(direction, {})
            new_data[cross_id][direction] = {}

            if not isinstance(dir_data, dict):
                continue

            for duration in sort_time_keys(dir_data.keys()):
                duration_data = dir_data.get(duration, {})

                if not isinstance(duration_data, dict):
                    continue

                compressed = compress_one_duration(duration_data)

                duration=str(int(duration)+5)#补一下那个缺失的时间
                new_data[cross_id][direction][duration] = compressed

    return new_data


def main():
    input_file = LIB_DIR / "chi_lan.json"
    output_file = LIB_DIR / "chi_lan_new.json"

    with input_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    new_data = compress_chi_lan(data)

    # 打印到终端
    print(json.dumps(new_data, ensure_ascii=False, indent=2))

    # 同时保存到文件
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    print(f"\n已输出到文件: {output_file}")


if __name__ == "__main__":
    main()
