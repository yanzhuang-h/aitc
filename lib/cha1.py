import json
import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent  # lib 目录
info = BASE_DIR / "cross_info.json"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JIYAN_PATH = os.path.join(BASE_DIR, "wwx.json")
with open(info, 'r',encoding='utf-8') as f:
    lines3=json.load(f)
print(lines3)
def jiangyan_biao_get(road_id):
    with open(JIYAN_PATH, "r", encoding="utf-8") as f:
        data= json.load(f)
    return data[road_id]


def quihe(L_set,L):
    sum=0
    for lan in L_set:
        sum+=L[lan]
    return sum
def   chuli_shuju(road_id, flow_map_single_intersection, extend_map_single_intersection):

    liu={
        'U':[0]*10,
        'D': [0] * 10,
        'L': [0] * 10,
        'R': [0] * 10,
        'UTL': [0] * 10,
        'DTL': [0] * 10,
        'LTL': [0] * 10,
        'RTL': [0] * 10,
    }
    zhuangtai_set=set()

    for x in extend_map_single_intersection:
        print(extend_map_single_intersection[x],x,"asdsad",extend_map_single_intersection[x][0]['time'])
        zhuangtai_set.add(extend_map_single_intersection[x][0]['curStageNo'])




    for x in flow_map_single_intersection:
        print(flow_map_single_intersection[x]['pass'],"asdsad")
        for d in ['U','D','L','R']:
            for i in range(len(flow_map_single_intersection[x]['pass'][d])):
                liu[d][i]+= flow_map_single_intersection[x]['pass'][d][i]

    yingshe_1 = {
        "UD": ["U", "D"],
        "LR": ["L", "R"],
        "RL": ["R", "L"],
        "DU": ["U", "D"],

        "UDL": ["UTL", "DTL"],
        "LRL": ["LTL", "RTL"],
        "DUL": ["UTL", "DTL"],
        "L":["LTL","L"],
        "D": ["DTL", "D"],
        "U": ["UTL", "U"],
        "R": ["RTL", "R"],

    }
    print(liu)

    str={
        'U':0,
        'D':0,
        'L':0,
        'R':0,
        'UTL':0,
        'DTL':0,
        'LTL':0,
        'RTL':0,
    }
    print(zhuangtai_set,"uweweyudsnabksjd",road_id,"ksdjsakldjsakldsjadlksadjsalkdsajdslka")
    for x in zhuangtai_set:
        try:
            if x in lines3[road_id]['phase']:
                juti=yingshe_1[lines3[road_id]['phase'][x]]
                print(lines3[road_id]['phase'][x],juti,"wewebhjgsd")
                for d in juti:
                    print(d)
                    str[d]=1

        except:
            continue
    print(str,"kjsahdkjasdhkjashdksedsadasdsadj")

    jingyan_biao=jiangyan_biao_get(road_id)
    # print(jingyan_biao['U'],"nijdksdsdskdjsdkjsdkj")

    sch={
        'U':0,
        'D':0,
        'L':0,
        'R':0,
        'UTL':0,
        'DTL':0,
        'LTL':0,
        'RTL':0,
    }
    for d in jingyan_biao:

        if d in  ['UTL','DTL','LTL','RTL'] and str[d]!=0:
            dd = d[0]
            t = 0
            L_lan = set()
            for lan, fuhao in lines3[road_id]['LaneNo'][dd].items():
                if fuhao == "1C":
                    L_lan.add(int(lan))


            for time, key in jingyan_biao[d].items():

                # print(L_lan,liu[dd],quihe(L_lan,liu[dd]),"inytysdkjsahduwey")
                if int(quihe(L_lan,key) * 0.8) >= quihe(L_lan,liu[dd]):
                    sch[d] = int(time)+6
                    t = 1
                    break

                if t == 0:
                    k, v = next(reversed(jingyan_biao[dd].items()))
                    sch[d] = int(k)


        else:

            t = 0
            for time, key in jingyan_biao[d].items():

                if int(sum(key) * 0.8) >= sum(liu[d]):
                    sch[d] = int(time)
                    t = 1
                    break
                if t == 0:
                    k, v = next(reversed(jingyan_biao[d].items()))
                    sch[d] = int(k)



    for d,zhi in str.items():
        if zhi==0:
            sch[d]=0



    print(liu,"sadsakldghueryuencvbjhfdghduyyuyryertji")
    sch1=[0]*10
    i=0
    for d,zhi in sch.items():
       sch1[i]=zhi
       i+=1
    print(sch,"oiuoiweyusdgsakjd",road_id,sch1)
    return sch1



def   chuli_shuju3(road_id, flow_map_single_intersection):

    liu={
        'U':[0]*10,
        'D': [0] * 10,
        'L': [0] * 10,
        'R': [0] * 10,
        'UTL': [0] * 10,
        'DTL': [0] * 10,
        'LTL': [0] * 10,
        'RTL': [0] * 10,
    }







    for x in flow_map_single_intersection:
        print(flow_map_single_intersection[x]['pass'],"asdsad")
        for d in ['U','D','L','R']:
            for i in range(len(flow_map_single_intersection[x]['pass'][d])):
                liu[d][i]+= flow_map_single_intersection[x]['pass'][d][i]
    print(liu,"huybcbytyewilsafhkjshdlasiuwewe")
    yingshe_1 = {
        "UD": ["U", "D"],
        "LR": ["L", "R"],
        "RL": ["R", "L"],
        "DU": ["U", "D"],

        "UDL": ["UTL", "DTL"],
        "LRL": ["LTL", "RTL"],
        "DUL": ["UTL", "DTL"],

    }
    print(liu)

    str={
        'U':0,
        'D':0,
        'L':0,
        'R':0,
        'UTL':0,
        'DTL':0,
        'LTL':0,
        'RTL':0,
    }

    # # for x in zhuangtai_set:
    # #     try:
    # #         if x in lines3[road_id]['phase']:
    # #             juti=yingshe_1[lines3[road_id]['phase'][x]]
    # #             print(lines3[road_id]['phase'][x],juti,"wewebhjgsd")
    # #             for d in juti:
    # #                 print(d)
    # #                 str[d]=1
    # #
    # #     except:
    # #         continue
    #
    #
    jingyan_biao=jiangyan_biao_get(road_id)
    print(jingyan_biao['U'],"nijdksdsdskdjsdkjsjkdhksjdhskjdhsakjdhsakadsdkj")
    #
    sch={
        'U':0,
        'D':0,
        'L':0,
        'R':0,
        'UTL':0,
        'DTL':0,
        'LTL':0,
        'RTL':0,
    }

    for d in jingyan_biao:

        if d in  ['UTL','DTL','LTL','RTL']:
            dd = d[0]
            t = 0
            L_lan = set()
            for lan, fuhao in lines3[road_id]['LaneNo'][dd].items():
                if fuhao == "1C":
                    L_lan.add(int(lan))


            for time, key in jingyan_biao[d].items():


                if int(quihe(L_lan,key) * 0.8) >= quihe(L_lan,liu[dd]):
                    sch[d] = int(time)+6

                    t = 1
                    break
                if t == 0:
                    k, v = next(reversed(jingyan_biao[dd].items()))
                    sch[d] = int(k)
            print(d,sch[d], "inytysdkjsahduweysjduweyuwnsjdgsfbdmsl")
        else:
            t = 0
            for time, key in jingyan_biao[d].items():

                if int(sum(key) * 0.8) >= sum(liu[d]):
                    sch[d] = int(time)
                    t = 1
                    break
                if t == 0:
                    k, v = next(reversed(jingyan_biao[d].items()))
                    sch[d] = int(k)
            print(d, sch[d], "inytysdkjsahduweysjduweyuwnsjdgsfbdmsl")


    # for d,zhi in str.items():
    #     if zhi==0:
    #         sch[d]=0




    sch1=[0]*10
    i=0
    for d,zhi in sch.items():
       sch1[i]=zhi
       i+=1
    print(sch1,"husdywuehskjdshdskjdshd")
    return sch1

