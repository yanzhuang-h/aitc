
import json
from pathlib import Path
import time
import os
from datetime import datetime, timedelta
from numba.cuda import laneid

data = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.abspath(os.path.join(BASE_DIR, os.pardir))
PROJECT_ROOT = os.path.abspath(os.path.join(LIB_DIR, os.pardir))
JIYAN_PATH = os.path.join(LIB_DIR, "beiyong1.json")

flow_path = os.path.join(PROJECT_ROOT, "logs_data", "flow", data + '_flow.txt')

extend_path = os.path.join(PROJECT_ROOT, "logs_data", "extend", data + '_extend.txt')
# stage_path="Stage_data\\" +data + '_stage.txt'
info = os.path.join(LIB_DIR, "cross_info.json")
with open(info, 'r',encoding='utf-8') as f:
    lines3=json.load(f)
with open(flow_path, 'r',encoding='utf-8') as f:
    lines1 = f.readlines()
with open(extend_path, 'r',encoding='utf-8') as f:
    lines2 = f.readlines()


def save_json(road_id):
    if not os.path.exists(JIYAN_PATH):
        print("经验表文件不存在:", JIYAN_PATH)
        return {}
    with open(JIYAN_PATH, "r", encoding="utf-8") as f:
        data_old= json.load(f)

    return data_old[road_id]
def Replace_data(data,road_id):
    if not os.path.exists(JIYAN_PATH):
        print("经验表文件不存在:", JIYAN_PATH)
        return {}
    with open(JIYAN_PATH, "r", encoding="utf-8") as f:
        data_old= json.load(f)
    data_old[road_id] = data

    with open(JIYAN_PATH, "w", encoding="utf-8") as f:
        json.dump(data_old, f, ensure_ascii=False, indent=2)


def new_data_get(road_id):

    with open(os.path.join(LIB_DIR, "chi_lan_new.json"), "r", encoding="utf-8") as f:
        zong = json.load(f)
    zong_road=zong[road_id]


    shuju={
        "U":{},
        "D":{},
        "L":{},
        "R":{},
        "UTL": {},
        "DTL": {},
        "LTL": {},
        "RTL": {}

    }

    # for d in zong_road:
    #     for time,zhi in zong_road[d].items():
    #         lanshuju=[0]*10
    #         for lan,shuzu in zhi.items():
    #             if shuzu!=[]:
    #              lanshuju[int(lan)]=next(iter(shuzu[int(len(shuzu)*0.8)]))
    #             # print(lanshuju)
    #         shuju[d][time]=lanshuju


    return zong_road


def Update_data(road_id):
    #取新的数据
    new_data=new_data_get(road_id)
    #提取旧数据经验表里的数据
    old_data=save_json(road_id)
    print("旧数据:",old_data)
    print("新数据：",new_data)
    for d,zhi in new_data.items():

        for time,shuzhi in zhi.items():
            if int(time)<=15:
                if time not in old_data[d]:
                    old_data[d][time]=new_data[d][time]
                else:
                    for i in range(10):
                        old_data[d][time][i]=int(new_data[d][time][i]*0.2+old_data[d][time][i]*0.8)

    print("更新后数据",old_data)
    Replace_data(old_data,road_id)





road_id={
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
for i in road_id:
    Update_data(i)
    pass
