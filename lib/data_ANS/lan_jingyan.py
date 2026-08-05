import json
from pathlib import Path
import time
import os
from datetime import datetime, timedelta
# from numba.cuda import laneid

# data = '2026-02-18'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.abspath(os.path.join(BASE_DIR, os.pardir))
PROJECT_ROOT = os.path.abspath(os.path.join(LIB_DIR, os.pardir))
JIYAN_PATH = os.path.join(LIB_DIR, "chi_lan.json")
#
# flow_path = "Flow_data\\" +data  + '_flow.txt'
#
# extend_path = "Extend_data\\" +data + '_extend.txt'
# # stage_path="Stage_data\\" +data + '_stage.txt'
info = os.path.join(LIB_DIR, "cross_info.json")
with open(info, 'r',encoding='utf-8') as f:
    lines3=json.load(f)
# with open(flow_path, 'r',encoding='utf-8') as f:
#     lines1 = f.readlines()
# with open(extend_path, 'r',encoding='utf-8') as f:
#     lines2 = f.readlines()
# datas = ['2026-02-03','2026-02-04','2026-02-05','2026-02-06','2026-02-07','2026-02-08','2026-02-09','2026-02-14','2026-02-11','2026-02-15','2026-02-16','2026-02-17','2026-02-18','2026-02-19','2026-02-20','2026-02-21','2026-02-22','2026-02-23','2026-02-24','2026-02-25','2026-02-26']
datas = [(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')]

for data in datas:

    flow_path = os.path.join(PROJECT_ROOT, "logs_data", "flow", data + '_flow.txt')
    extend_path = os.path.join(PROJECT_ROOT, "logs_data", "extend", data + '_extend.txt')

    with open(flow_path, 'r', encoding='utf-8') as f:
        lines1 = f.readlines()

    with open(extend_path, 'r', encoding='utf-8') as f:
        lines2 = f.readlines()

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


    # 排序每个路口每个方向的时间
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


    def filter_abnormal_zhongbiao(zhongbiao, kaishi_time):
        hour = time.localtime(kaishi_time).tm_hour

        if not (5 <= hour <= 23):
            return zhongbiao

        filtered = {}

        for direction, time_map in zhongbiao.items():
            kept = {}

            for t, liu in time_map.items():
                if int(t) != 0 and sum(liu) == 0:
                    print(f"白天异常数据，已过滤: direction={direction}, time={t}, liu={liu}")
                    continue

                kept[t] = liu

            if kept:
                filtered[direction] = kept

        return filtered


    def sort_sum11(data):
        """
        对每个 direction -> time -> lane 中的车辆经验进行排序
        排序规则：按车辆数(key)从小到大
        """

        for direction, times in data.items():

            for time_key, lanes in times.items():

                for lane_id, car_list in lanes.items():

                    if not car_list:
                        continue

                    car_list.sort(
                        key=lambda x: int(next(iter(x)))
                    )

        return data

    def load_json(road_id):
        if not os.path.exists(JIYAN_PATH):
            print("经验表文件不存在:", JIYAN_PATH)
            return {}
        with open(JIYAN_PATH, "r", encoding="utf-8") as f:
            data= json.load(f)
        if road_id not in data:
            return {}
        return data[road_id]



    def merge_zhongbiao(old_data: dict, new_data: dict,road_id) -> dict:
        if old_data == {}:
            return new_data


        for d,value in new_data.items():

            for i in value:

              if str(i) not in old_data[d]:# 没有的情况

                  old_data[d][str(i)]=value[i]
              else:
                  if sum(old_data[d][str(i)])<sum(value[i]):
                      old_data[d][str(i)]=value[i]

        return old_data
    def sort_sum(data):
        """
        对所有方向下的 time 数据排序
        """
        for direction in data:
            for time_key, value in data[direction].items():
                data[direction][time_key] = sorted(
                    value,
                    key=lambda x: sum(x)
                )

        return data
    def add_data(old_data,new_data,road_id,zongtime,kaishi_zhen,end):
        # print("_______________")
        # print(old_data)
        # print(new_data)

        if old_data == {}:
            old_data = {
                "U":{},
                "D":{},
                "L":{},
                "R":{},
                "UTL": {},
                "DTL": {},
                "LTL": {},
                "RTL":{}

            }
        for d,value in new_data.items():
            for time,liu in value.items():
                if str(time) not in old_data[d]:
                    old_data[d][str(time)] = {
                    "1":[],
                    "2":[],
                    "3":[],
                    "4": [],
                    "5": [],
                    "6": [],
                    "7": [],
                    "8": [],
                    "9": [],
                    "0":[]
                    }
                for i in range(len(liu)):
                    if liu[i]!=0:
                     shuju={
                         str(liu[i]):{
                         "stage":kaishi_zhen,
                         "end":end,
                         "zongtime":zongtime
                     }
                     }
                     old_data[d][str(time)][str(i)].append(shuju)

        return old_data

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
    def jiagong(flow,dict_id,road_id,diyici):
        # print()
        # print(dict_id)
        jianyan = {
            'L': {},
            'R': {},
            'U': {},
            'D': {},
            'UTL': {},
            'DTL': {},
            'LTL': {},
            'RTL': {}
        }

        yingshe_1 = {
            "UD": ["U", "D"],
            "LR": ["L", "R"],
            "UDL": ["UTL", "DTL"],
            "LRL": ["LTL", "RTL"],
            "U": ["U", "UTL"],
            "D": ["D", "DTL"],
            "L": ["L", "LTL"],
            "R": ["R", "RTL"],
            "LTD":['LTL',"D"]#西左+南行
        }
        kaishi_time,jieshu_time=0,0

        jieshu_time=int(flow[-1]['time'])//1000
        if len(flow[0]['time'])>12:
            kaishi_time=int(flow[0]['time'])//1000
        else:
            kaishi_time=int(flow[0]['time'])
        if len(flow[-1]['time']) >= 12:
            jieshu_time = int(flow[-1]['time']) // 1000
        else:
            jieshu_time = int(flow[-1]['time'])

        L=0
        R=0
        U=0
        D=0
        LTL=0
        RTL=0
        UTL=0
        DTL=0


            # print(lines3[road_id]['phase'][phase])


        dangxia_set = set()
        tt=0
        kaishi_zhen=0

        kaishi_xiangwei11="-1"
        for i in range(kaishi_time, jieshu_time):
            ts=i
            if ts in dict_id:
                phase = dict_id[ts]
            elif ts - 1 in dict_id:
                phase = dict_id[ts - 1]
            elif ts + 1 in dict_id:
                phase = dict_id[ts + 1]
            elif ts - 2 in dict_id:
                phase = dict_id[ts - 2]
            elif ts + 2 in dict_id:
                phase = dict_id[ts + 2]
            else:
                continue

            if kaishi_xiangwei11=="-1":
                kaishi_xiangwei11=phase

            if phase!=kaishi_xiangwei11 and phase!="-1":
                kaishi_zhen=ts
                break
        if kaishi_zhen==0:
            kaishi_zhen=kaishi_time
        # print(kaishi_time,kaishi_zhen,jieshu_time,"uyiuiyiuyiu")
        zhuangtai_set = set()
        for i in range(kaishi_zhen, jieshu_time):
            ts = i

            if ts in dict_id:
                phase = dict_id[ts]
            elif ts - 1 in dict_id:
                phase = dict_id[ts - 1]
            elif ts + 1 in dict_id:
                phase = dict_id[ts + 1]
            elif ts - 2 in dict_id:
                phase = dict_id[ts - 2]
            elif ts + 2 in dict_id:
                phase = dict_id[ts + 2]
            else:

                continue

            if phase in lines3[road_id]['phase']:
                zhuangtai_set.add(lines3[road_id]['phase'][phase])
                # print(lines3[road_id]['phase'][phase],ts-kaishi_zhen)
        zhouqi=0
        zongtime=0
        end=0
        kaishi_xiangwei="-1"

        pro="-1"
        dangqian="-1"
        for i in range(kaishi_zhen,jieshu_time):

            ts = i

            if ts in dict_id:
                phase = dict_id[ts]
            elif ts - 1 in dict_id:
                phase = dict_id[ts - 1]
            elif ts + 1 in dict_id:
                phase = dict_id[ts + 1]
            elif ts - 2 in dict_id:
                phase = dict_id[ts - 2]
            elif ts + 2 in dict_id:
                phase = dict_id[ts + 2]
            else:
                #print("ts数据不存在没有",i-kaizhen,phase)
                phase=pro
                print("ts数据不存在没有", i - kaishi_zhen, phase)
            # print("ts", i - kaishi_zhen, phase,len(dangxia_set),len(zhuangtai_set))
            if phase not in lines3[road_id]['phase'] and phase !="-1":
                 print(phase,road_id)
                 pass
            if phase in lines3[road_id]['phase']:

                if kaishi_xiangwei=="-1":
                    kaishi_xiangwei=phase
                pro=phase
                xiangwei = lines3[road_id]['phase'][phase]
                dangxia_set.add(lines3[road_id]['phase'][phase])
                # 看相位
                #print(i-kaishi_zhen,xiangwei)
                if xiangwei not in yingshe_1:
                    continue
                for d in yingshe_1[xiangwei]:
                    if d=='U':
                        U+=1
                    elif d=='D':
                        D+=1
                    elif d=='L':
                        L+=1
                    elif d=='R':
                        R+=1
                    elif d=='UTL':
                        UTL+=1
                    elif d=='DTL':
                        DTL+=1
                    elif d=='LTL':
                        LTL+=1
                    elif d=='RTL':
                        RTL+=1


            if (phase=="-1" or kaishi_xiangwei==phase ) and dangxia_set and zhuangtai_set:
                if len(dangxia_set)==len(zhuangtai_set):
                    zhouqi+=1
                    if zhouqi==1:#选择周期用的方法
                        zongtime=i-kaishi_zhen
                        end=i
                        break
                    else:
                        dangxia_set=set()
        # print(U+D+L+R+UTL+DTL+LTL+RTL)
        print("--------------------------------------------")
        liuliang={
            'L': [0]*10,
            'R': [0]*10,
            'U': [0]*10,
            'D': [0]*10,
            'UTL': [0]*10,
            'DTL': [0]*10,
            'LTL': [0]*10,
            'RTL': [0]*10,
        }
        str={
            'L': L,
            'R': R,
            'U': U,
            'D': D,
            'UTL': UTL,
            'DTL': DTL,
            'LTL': LTL,
            'RTL':RTL
        }
        for x in flow:

            if (x['jtll_ddbh'] not in lines3[road_id]['jtll_ddbh']) :
                print ("缺失方向符号",x['jtll_ddbh'],road_id)
                continue
            ti11=int(x["time"])//1000
            if ti11<kaishi_zhen or ti11>end:
                continue
            # liuliang[lines3[road_id]['jtll_ddbh'][x['jtll_ddbh']]][x['lan']]+=1

            direction = lines3[road_id]['jtll_ddbh'][x['jtll_ddbh']]
            lane = int(x['lan'])

            if 0 <= lane < 10:
                liuliang[direction][lane] += 1
            else:
                print(f"非法车道号: road_id={road_id}, lane={lane}, record={x}")
                continue

            for d in "UDLR":
                xin=d+'TL'
                if str[xin]>0:
                 for lan in range(10):

                    liuliang[xin][lan]=liuliang[d][lan]
        if zongtime==0:
            return 0

        for d in "UDLR":
            xin=d+'TL'
            for lan in range(10):
                liuliang[xin][lan]=liuliang[d][lan]*(600//zongtime)
                liuliang[d][lan]=liuliang[d][lan]*(600//zongtime)
        if U!=0:
            U+=3
        if D!=0:
            D+=3
        if L!=0:
            L+=3
        if R!=0:
            R+=3

        if UTL!= 0:
            UTL += 3
        if DTL != 0:
            DTL += 3
        if LTL != 0:
            LTL += 3
        if RTL != 0:
            RTL += 3

        if road_id!="1700275":
            zhongbiao={
                'U':{
                    U:liuliang['U']#-1状态有4s是放行的时间，就跟怪,所有加3-5s
                },
                'D':{
                    D: liuliang['D']
                },
                'L': {
                    L: liuliang['L']
                },
                'R': {
                    R: liuliang['R']
                },
                'RTL': {
                    RTL: liuliang['RTL']
                },
                'LTL': {
                    LTL: liuliang['LTL']
                },
                'UTL': {
                    UTL: liuliang['UTL']
                },
                'DTL': {
                    DTL: liuliang['DTL']
                },
            }
        else:
            zhongbiao = {
                'U': {
                    U // 6: liuliang['U']
                },
                'D': {
                    D // 6: liuliang['D']
                },
                'L': {
                    L // 6: liuliang['L']
                },
                'R': {
                    R // 6: liuliang['R']
                },
                'RTL': {
                    RTL // 6: liuliang['RTL']
                },
                'LTL': {
                    LTL // 6: liuliang['LTL']
                },
                'UTL': {
                    UTL // 6: liuliang['UTL']
                },
                'DTL': {
                    DTL // 6: liuliang['DTL']
                },
            }
        print(time.localtime(kaishi_time),road_id)

        for d,key in zhongbiao.items():

            for time1,shuzu in key.items():
                if int(time1)<=10 and sum(shuzu)!=0:

                    zhongbiao[d][time1]=[0]*10
        print(zhongbiao)
        zhongbiao = filter_abnormal_zhongbiao(zhongbiao, kaishi_time)

        print(zhongbiao)
        print(zhongbiao)

        lao = load_json(road_id)
        # print(lao)

        data = add_data(lao, zhongbiao, road_id,zongtime,kaishi_zhen,end)
        # data=sort_sum(data)
        data=sort_sum11(data)
        save_json(data, road_id)

        # print("_______________________________________________________________________________________________________________________________________________________________________________________________________________________________")

    extend= {}

    s1=set()
    for line in lines2:
        try:
            data = json.loads(line)
            # ti = int(int(data['ts'])//1000)
            s1.add(data['CrossId'])
            if data['CrossId'] not in extend:
                extend[data['CrossId']] = []

            xuyao={}
            # xuyao['CrossId'] = data['CrossId']
            # xuyao['time']=data['time']
            # xuyao['curStageNo'] = data['curStageNo']
            xuyao[int(data['time'])//1000] = data['curStageNo']
            extend[data['CrossId']].append(xuyao)

        except:
            continue

    print(s1)
    # for road in extend:
    #     if road=='1300047':
    #         print(extend[road])
    s2=set()

    flow={}

    for line in lines1:
        try:
            data = json.loads(line)
            cord_id=''
            for id in lines3:

                if data['jtll_ddbh'] in lines3[id]['jtll_ddbh']:

                    cord_id=id

                    break
            xuyao={}
            if cord_id not in flow:
                flow[cord_id] =[]

            xuyao={}
            xuyao['CrossId'] = cord_id
            xuyao['time']=data['ts']
            xuyao['jtll_ddbh']=data['jtll_ddbh']
            xuyao['lan'] = int(data['ycsb_cdbh'])
            xuyao['ycsb_xsfx']=data['ycsb_xsfx']
            flow[cord_id].append(xuyao)
        except:
            continue




    s2=set()
    # s2.add('1300068')

    for x in shipin_roid:
        s2.add(x)
    print(s2)
    u=0
    diyici=0
    # for road_id in s2:
    #     flow1=[]
    #     t=0
    #     last=0
    #     dict_id={}
    #     for x in extend[road_id]:#直接把一个路口的状态记录{时间：状态}
    #         # print(x)
    #         for key,zhi in x.items():
    #             # print(key,zhi)
    #             # print(key)
    #             dict_id[int(key)]=zhi
    for road_id in s2:
        flow1 = []
        t = 0
        last = 0
        road_extend = extend.get(road_id, [])
        road_flow = flow.get(road_id, [])

        if not road_extend:
            print(f"路口缺少阶段数据: road_id={road_id}")
            continue

        dict_id = {}
        for x in road_extend:
            for key, zhi in x.items():
                dict_id[int(key)] = zhi

        for tiao in road_flow:

            if t==0:
                t=1
                last=int(tiao['time'])//1000

            if last+300<=(int(tiao['time'])//1000):
                diyici+=1

                # print(time.localtime(int(tiao['time'])//1000))
                # if u==0:
                #     u=1
                #     print(flow1)
                #     flow1=[]
                #     print(flow1)
                # if diyici==1:
                if diyici:
                    jiagong(flow1,dict_id,road_id,diyici)
                flow1=[]
                last=int(tiao['time'])//1000
            flow1.append(tiao)

        sort_zhong()
