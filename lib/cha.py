
import json
import bisect
import os
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JIYAN_PATH = os.path.join(BASE_DIR, "sorted_jiyan_result3.json")
CROSS_INFO_PATH = os.path.join(BASE_DIR, "cross_info.json")

# 工具函数
import faulthandler

# faulthandler.dump_traceback_later(
#     timeout=10,      # 每 10 秒打印一次
#     repeat=True      # 一直重复
# )
def empty_vec():
    return [0] * 10

def add_vec(a, b):
    return [a[i] + b[i] for i in range(10)]

def sum_vec(v):
    return sum(v)

# 加载经验表
def load_jiyan():
    if not os.path.exists(JIYAN_PATH):
        print("经验表文件不存在:", JIYAN_PATH)
        return {}
    with open(JIYAN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)



def reverse_time_from_three_cycle(cross_id, flow_map, stage_map):
    try:
        jiyan = load_jiyan()
        if cross_id not in jiyan:
            print("经验表缺失:", cross_id)
            return None


        with open(CROSS_INFO_PATH, "r", encoding="utf-8") as f:
            cross_info = json.load(f)
        print("222222222222222222222222222222222222222222222")
        phase_map = cross_info[cross_id]["phase"]


        stages = []
        for _, lst in stage_map.items():
            if not lst:
                continue
            # print("ssssdasfsdfdasfasdfsdfdsfasdfdsafsda")
            rec = lst[0]  # stageMap 格式是 list 包 dict
            ts = int(rec["time"]) // 1000
            no = int(rec["curStageNo"])
            if no > 0:
                stages.append((ts, no))


        if len(stages) < 6:
            print("阶段节点不足:", cross_id)
            return None

        stages.sort()

        # 压缩重复相位
        merged = []
        for ts, no in stages:
            if not merged or merged[-1][1] != no:
                merged.append((ts, no))
        # print(merged,len(merged))
        if len(merged) < 6:
            print("压缩后阶段不足:", cross_id)
            return None

        phase_seq = [no for _, no in merged]
        print("4444444444444444444444444444444444444444")
        ###############################################################
        # 4. 识别单周期 pattern
        ###############################################################
        pattern = [phase_seq[0]]
        for p in phase_seq[1:]:
            if p == pattern[0]:
                break
            pattern.append(p)

        cycle_len = len(pattern)
        need_nodes = cycle_len * 3 + 1


        start_index = None
        L = len(phase_seq)
        for s in range(L - need_nodes + 1):
            ok = True
            for j in range(need_nodes - 1):
                if phase_seq[s + j] != pattern[j % cycle_len]:
                    ok = False
                    break
            if ok:
                start_index = s
                break

        if start_index is None:
            print("未找到三个完整周期:", cross_id)
            return None


        try:
            flow_items = [(int(ts), v) for ts, v in flow_map.items()]
            flow_items.sort()

            MAX_FLOW_ITEMS = 5000
            if len(flow_items) > MAX_FLOW_ITEMS:
                flow_items = flow_items[-MAX_FLOW_ITEMS:]

            flow_times = [ts for ts, _ in flow_items]
        except:
            print("flow_map key 不是 timestamp:", flow_map.keys())
            return None


        phase_flow_sum = [defaultdict(empty_vec) for _ in range(cycle_len)]
        total_duration = [0] * cycle_len

        for c in range(3):
            for i in range(cycle_len):
                idx = start_index + c * cycle_len + i
                ts_start = merged[idx][0]
                ts_end = merged[idx + 1][0]
                print("阶段1-------------------")
                dur = ts_end - ts_start
                print(ts_start,ts_end,dur,"时间间隔")
                if dur <= 0:
                    continue
                total_duration[i] += dur

                L = bisect.bisect_left(flow_times, ts_start)
                R = bisect.bisect_left(flow_times, ts_end)

                for pos in range(L, R):
                    _, item = flow_items[pos]
                    print(_,item)
                    for base in ["U", "D", "L", "R"]:
                        for k in range(len(item["pass"][base])):
                            phase_flow_sum[i][base][k] += item["pass"][base][k]
                # print("阶段2————————————————————————————————")
        # print("777777777777777777777777777777777777777777777777777777777777777777777")
        total_cycle_time = sum(total_duration)
        if total_cycle_time <= 0:
            print("周期为空:", cross_id)
            return None

        ###############################################################
        # 8. phase → 8 方向映射
        ###############################################################
        PHASE_TO_DIR = {
            "UD": ["U", "D"],
            "LR": ["L", "R"],
            "UDL": ["UTL", "DTL"],
            "LRL": ["LTL", "RTL"],
            "U": ["U", "UTL"],
            "D": ["D", "DTL"],
            "L": ["L", "LTL"],
            "R": ["R", "RTL"],
        }

        BASE = {
            "U": "U", "UTL": "U",
            "D": "D", "DTL": "D",
            "L": "L", "LTL": "L",
            "R": "R", "RTL": "R",
        }

        final_flow = {
            d: [0] * 10 for d in ["U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL"]
        }

        for i in range(cycle_len):
            phase_no = pattern[i]
            phase_name = phase_map[str(phase_no)]
            dirs = PHASE_TO_DIR[phase_name]

            for d in dirs:
                base = BASE[d]
                for k in range(10):
                    final_flow[d][k] += phase_flow_sum[i][base][k]
        # print("8888888888888888888888888888888888888888888888888888888888888888888888888888888")
        ###############################################################
        # 9. 折算成 10 分钟 (600 秒)
        ###############################################################
        scaled_flow = {}
        for d, vec in final_flow.items():
            scaled_flow[d] = [ round(x * 600 / total_cycle_time) for x in vec ]
        print(total_cycle_time,"总时间多少")
        ###############################################################
        # 10. 查经验表反推时间
        ###############################################################
        result = {}
        for d, vec in scaled_flow.items():
            table = jiyan[cross_id].get(d, {})
            if not table:
                result[d] = None
                continue

            S = sum(vec)+10
            times = sorted(int(t) for t in table.keys())

            chosen = None
            for t in times:
                if sum(table[str(t)]) >= S:
                    chosen = t
                    break
            if chosen is None:
                chosen = times[-1]
            print(d, S, vec,chosen)
            result[d] = chosen

        sch=[]
        for d in result:
            if result[d] is not None:
                sch.append(result[d])
            else:
                sch.append(0)
        sch.append(0)
        sch.append(0)
        print(result, "kjsdhkjsasasasasasasasasasasasasasasasa",sch)
        return sch
    except:
        return None





