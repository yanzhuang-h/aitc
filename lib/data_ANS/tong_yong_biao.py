import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LIB_DIR = BASE_DIR.parent


def get_pool(zongtime):
    """根据周期返回经验池名称"""
    if zongtime < 80:
        return "xiao1"
    elif zongtime < 100:
        return "xiao2"
    elif zongtime < 120:
        return "zhong1"
    elif zongtime < 140:
        return "zhong2"
    elif zongtime <= 160:
        return "da1"
    else:
        return "da2"


def sort_pool(pool):
    """对经验池进行排序"""
    for direction in pool:
        for time_key in pool[direction]:
            lanes = pool[direction][time_key]

            for lane in lanes:
                car_list = lanes[lane]

                car_list.sort(
                    key=lambda x: int(next(iter(x)))
                )


def main():

    with open(LIB_DIR / "chi_lan.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    result = {
        "xiao1": {},
        "xiao2": {},
        "zhong1": {},
        "zhong2": {},
        "da1": {},
        "da2": {}
    }

    for cross_id in data:
        cross = data[cross_id]

        for direction in cross:

            for time_key in cross[direction]:

                lanes = cross[direction][time_key]

                for lane in lanes:

                    car_list = lanes[lane]

                    for item in car_list:

                        key = next(iter(item))
                        info = item[key]

                        zongtime = info["zongtime"]

                        pool_name = get_pool(zongtime)
                        pool = result[pool_name]

                        pool.setdefault(direction, {})
                        pool[direction].setdefault(time_key, {})
                        pool[direction][time_key].setdefault(lane, [])

                        pool[direction][time_key][lane].append(item)

    # 排序所有经验池
    for pool in result.values():
        sort_pool(pool)

    with open(LIB_DIR / "tongyong.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
