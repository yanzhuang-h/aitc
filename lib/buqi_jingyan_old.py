import json
import os
from pathlib import Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JIYAN_PATH = os.path.join(BASE_DIR, "chi_lan_new.json")
def jiangyan_biao_get(road_id):
    with open(JIYAN_PATH, "r", encoding="utf-8") as f:
        data= json.load(f)

    return data[road_id]

def zhao(liuliang):

    for i in range(len(liuliang)-1,-1,-1):
        if liuliang[i]!=0:
            return liuliang[i]
    return 0
def zhao_wei(d,road_id):
    # for i in range(len(liuliang)-1,-1,-1):
    #     if liuliang[i]!=0:
    #         return i


    for lan,fu in lines3[road_id]["LaneNo"][d].items():
            if fu=="1C":

                return int(lan)


    return  -1

def calc_tail_rise_value(last_val, dt,
                         post_min_rise=0.08,
                         post_max_rise=0.25,
                         peak_extra_cap=8.0,
                         peak_val=None):
    """
    峰值后目标值：
    继续缓慢上升，不下降，也不暴涨
    """
    lower = last_val + post_min_rise * dt
    upper = last_val + post_max_rise * dt

    new_val = lower

    if peak_val is not None:
        new_val = min(new_val, peak_val + peak_extra_cap)

    # 双保险，确保不超过本段最大允许涨幅
    new_val = min(new_val, upper)
    return new_val

info="cross_info.json"
with open(info, 'r',encoding='utf-8') as f:
    lines3=json.load(f)

def save_json(data,road_id):
    if not os.path.exists(JIYAN_PATH):
        print("经验表文件不存在:", JIYAN_PATH)
        return {}
    with open(JIYAN_PATH, "r", encoding="utf-8") as f:
        data_old= json.load(f)
    data_old[road_id] = data

    with open(JIYAN_PATH, "w", encoding="utf-8") as f:
        json.dump(data_old, f, ensure_ascii=False, indent=2)

def load_result(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}  # 如果文件不存在，则返回空字典


def sort_zhong():
    SAVE_PATH=JIYAN_PATH
    # 加载结果数据
    result_data = load_result(SAVE_PATH)
    # print(result_data)
    # 排序
    sorted_result = sort_by_time(result_data)

    # 打印排序后的结果
    # print(json.dumps(sorted_result, indent=2, ensure_ascii=False))

    # 如果需要保存排序后的结果，可以使用如下代码：
    with open(SAVE_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted_result, f, indent=2, ensure_ascii=False)
    print("排序完成已保存")


def sort_by_time(data):

    sorted_data = {}

    # 遍历每个路口的方向
    for cross_id, directions in data.items():
        sorted_data[cross_id] = {}

        for direction, time_dict in directions.items():
            sorted_data[cross_id][direction] = {}

            # 对每个方向的时间进行排序
            sorted_times = sorted(time_dict.keys(), key=int)  # 按时间排序，时间是字符串，使用int比较
            for time in sorted_times:
                sorted_data[cross_id][direction][time] = time_dict[time]

    return sorted_data



def buqijingyanbiaod(road_id):


    jingyanbiao=jiangyan_biao_get(road_id)


    # 看一下目前8个方向增大的流量在哪些时间里
    for d,zhi in jingyanbiao.items():

        print(d)
        pro=-1
        pro_time=0
        if d in ['U','D','L','R']:
            for time,liuliang in zhi.items():

                if sum(liuliang)>pro:
                    pro=sum(liuliang)

                    print(time,sum(liuliang),liuliang,end="|||||||")
            print()
        else:
            for time,liuliang in zhi.items():

                if zhao(liuliang)>pro:
                    pro=zhao(liuliang)
                    print(time,zhao(liuliang),end="|||||||")
            print()
        # print(d,min_time,min_zhi,max_time,max_zhi)
    #将两边内异常的值(中间都小于两边的值)进行线性增加


    gengxin={
        'U':{},
        'D':{},
        'L':{},
        'R':{},
        'UTL':{},
        'DTL':{},
        'LTL':{},
        'RTL':{}

    }

    for d, zhi in jingyanbiao.items():

        print(d)
        pro_liu = [0]*10
        pro_time = 0

        if d in ['U', 'D', 'L', 'R']:
            for time, liuliang in zhi.items():
                if sum(liuliang) > sum(pro_liu):
                    if pro_time==0:
                        pro_liu = list(liuliang)
                        pro_time = int(time)
                        continue
                    time=int(time)
                    ju=(sum(liuliang)-sum(pro_liu))/(time-pro_time)
                    ci=0
                    for i in range(pro_time+1,time):
                        ci=ci+1
                        gengxin[d][str(i)]=list(pro_liu)
                        gengxin[d][str(i)][0]+=ci*ju

                    pro_liu=list(liuliang)
                    pro_time = time

            print()
        else:

            c1 = zhao_wei(d[0], road_id)

            # 没有1C，说明没有左转专用车道，直接跳过
            if c1 == -1:
                print(f"{road_id} {d} 没有1C车道，跳过左转补齐")
                continue

            # 按时间排序
            items = sorted(zhi.items(), key=lambda x: int(x[0]))
            times = [int(t) for t, _ in items]
            vals = [liuliang[c1] for _, liuliang in items]

            if not times:
                continue

            # 找峰值：如果有多个最大值，默认取第一个最大值位置
            peak_idx = max(range(len(vals)), key=lambda i: vals[i])
            peak_time = times[peak_idx]
            peak_val = vals[peak_idx]

            print(f"{road_id} {d} 左转车道={c1} 峰值时间={peak_time} 峰值={peak_val}")

            # ---------------------------
            # A. 峰值前：完全按你原来的逻辑
            # ---------------------------
            pro_liu = [0] * 10
            pro_time = 0

            for idx in range(peak_idx + 1):
                time = times[idx]
                liuliang = list(items[idx][1])

                if liuliang[c1] > pro_liu[c1]:
                    if pro_time == 0:
                        pro_liu = list(liuliang)
                        pro_time = int(time)
                        continue

                    time_int = int(time)
                    if time_int <= pro_time:
                        pro_liu = list(liuliang)
                        pro_time = time_int
                        continue

                    ju = (liuliang[c1] - pro_liu[c1]) / (time_int - pro_time)

                    for i in range(pro_time + 1, time_int):
                        gengxin[d][str(i)] = list(pro_liu)
                        gengxin[d][str(i)][c1] = pro_liu[c1] + (i - pro_time) * ju

                    pro_liu = list(liuliang)
                    pro_time = time_int

            # ---------------------------
            # B. 峰值后：按参数做微缓上升
            # ---------------------------
            last_time = peak_time
            last_val = float(peak_val)

            # 峰值点本身也写回去，避免后面用旧值
            zhi[str(peak_time)][c1] = peak_val

            for idx in range(peak_idx + 1, len(items)):
                time = times[idx]
                dt = time - last_time

                if dt <= 0:
                    continue

                # 不再用原始值决定锚点，而是直接按参数微缓上升
                new_anchor = calc_tail_rise_value(
                    last_val=last_val,
                    dt=dt,
                    post_min_rise=0.08,  # 峰值后每秒至少涨多少
                    post_max_rise=0.25,  # 峰值后每秒最多涨多少
                    peak_extra_cap=8.0,  # 相比峰值，后段最多再多涨多少
                    peak_val=peak_val
                )

                # 先补中间缺失时间
                ju = (new_anchor - last_val) / dt
                prev_base = list(items[idx - 1][1])

                for i in range(last_time + 1, time):
                    gengxin[d][str(i)] = list(prev_base)
                    gengxin[d][str(i)][c1] = last_val + (i - last_time) * ju

                # 再把当前观测点本身也修成新的锚点
                zhi[str(time)][c1] = new_anchor

                last_time = time
                last_val = new_anchor




    print("jhsddddddddddddddddddd")
    for d,zhi in gengxin.items():
        print(d)
        for time,liuliang in zhi.items():
            print(time,liuliang," ")
            jingyanbiao[d][str(time)]=liuliang
        print()


    #
    # print(jingyanbiao)
    save_json(jingyanbiao, road_id)

    # for d,zhi in jingyanbiao.items():
    #     print(d)
    #     for time,liuliang in zhi.items():
    #         print(time,liuliang,end="|||")
    #     print()

shipin_roid={
    "2703062",
    "1300106",
    "1300047",
    "1300069",
    "1300042",
    "1300870",
    "1300101",
    # "1700086",
    # # "1700276",
    # "1700275",
    "1300229",
    "2712127",
    "2703062",
    "1300106",
    "1300092",
    "1300101",
    "1300042",
    "1300044",
}

#补齐经验表
for road_id in shipin_roid:
    buqijingyanbiaod(road_id)
sort_zhong()