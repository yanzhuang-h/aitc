from datetime import date

from chinese_calendar import is_workday
from lib.AITC_tool import *
from lib.cha import  *
import time
from  lib.cha1 import *
from lib.cha1 import chuli_shuju
from lib.data_ANS.flow_allocator_shadow import select_pilot_schedule

Cross_Video = {
    '1300069': {
        "Cross_type" : "Video"
    },
    '1300068':{
        "Cross_type" : "Video"
    },
    '2712127':{
        "Cross_type" : "Video"
    },
    '2703062':{
        "Cross_type" : "Video"
    },
    '1300106':{
        "Cross_type" : "Video"
    },
    '1300047':{
        "Cross_type" : "Video"
    },
    '1300103':{
        "Cross_type" : "Video"
    },
    '1300092':{
        "Cross_type" : "Video"
    },
    '1300101':{
        "Cross_type" : "Video"
    },
    '1300097':{
        "Cross_type" : "Video"
    },
    '1300044':{
        "Cross_type" : "Video"
    },
    '1300046':{
        "Cross_type" : "Video"
    },
    '1300042':{
        "Cross_type" : "Video"
    },
    '1300592':{
        "Cross_type" : "Video"
    },
    '1300644':{
        "Cross_type" : "Video"
    },
    '1300454':{
        "Cross_type" : "Video"
    },
    '1300451':{
        "Cross_type" : "Video"
    },'1300870':{
        "Cross_type" : "Video"
    },
    '1300271':{
        "Cross_type" : "Radar"
    },
    '1700086':{
        "Cross_type" : "Radar"
    },
    '1700275':{
        "Cross_type" : "Radar"
    },
    '1700276':{
        "Cross_type" : "Radar"
    },
    '1700087': {
        "Cross_type": "Radar"
    },
    '1300239': {
        "Cross_type": "Radar"
    },
    '1300229': {
        "Cross_type": "Radar"
    },
    '1700124': {
        "Cross_type": "Radar"
    },
    '1700125': {
        "Cross_type": "Radar"
    },
    '1700126': {
        "Cross_type": "Radar"
    },
    '1700079': {
        "Cross_type": "Radar"
    },
'1300153': {
        "Cross_type": "Radar"
    },
'1300166': {
        "Cross_type": "Radar"
    },
'1300306': {
        "Cross_type": "Radar"
    },
'1300409': {
        "Cross_type": "Radar"
    },





'1300362': {
        "Cross_type": "Radar"
    },

'1300087': {
        "Cross_type": "Radar"
    },

'1300147': {
        "Cross_type": "Radar"
    },



'2702736': {
        "Cross_type": "Radar"
    },
'1700262': {
        "Cross_type": "Radar"
    },


'1700085': {
        "Cross_type": "Radar"
    },


'1700067': {
        "Cross_type": "Radar"
    },


'1700293': {
        "Cross_type": "Radar"
    },


'1300364': {
    "Cross_type": "Radar"
},
'1300179': {
    "Cross_type": "Radar"
},
'1300094': {
    "Cross_type": "Radar"
},
'1300255': {
    "Cross_type": "Radar"
},
'1300039': {
    "Cross_type": "Radar"
},
'1300108': {
    "Cross_type": "Radar"
},
'1300266': {
    "Cross_type": "Radar"
},
'1300120': {
    "Cross_type": "Radar"
},
'1300230': {
    "Cross_type": "Radar"
},
'1300089': {
    "Cross_type": "Radar"
},
'1300067': {
    "Cross_type": "Radar"
},
'1300070': {
    "Cross_type": "Radar"
},
'1300086': {
    "Cross_type": "Radar"
},
'1300253': {
    "Cross_type": "Radar"
},
'1300358': {
    "Cross_type": "Radar"
},







}

Cross_Radar ={
    '1300271':{
        "Cross_type" : "Radar"
    }
}





def DQN_select(traffic_vector, queue_vector,traffic_vector_duration2,current_time,
               flow_map_single_intersection,queue_map_single_intersection,
               stage_map_single_intersection,last_coordinate_set,cur_flow_pre_map,
               cur_queue_pre_map,extend_map_single_intersection,
               overflowMap,radarMap_single_intersection,cross_id,boyan_map_single_intersection):
    # 初始化返回结果


    t = time.localtime(current_time)
    coordinate_map = {}  # 空字典
    model_info_list = {}  # 空字典
    EXP_list = {}  # 空字典
    if cross_id in Cross_Video:
        schedule = Get_time_map(cross_id)
        if not schedule:
            sch = [0] * 10
        else:
            sch = schedule.get(str(t[3]))
        if cross_id == '2703062':
            return DQN_select_2703062(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300451':
            return DQN_select_1300451(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300047':
            return DQN_select_1300047(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300068':
            return DQN_select_1300068(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection,0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300092':
            return DQN_select_1300092(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection,0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300106':
            return DQN_select_1300106(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection,0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '2712127':
            return DQN_select_2712127(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection,0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300097':
            return DQN_select_1300097(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300042':
            return DQN_select_1300042(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection,0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300454':
            return DQN_select_1300454(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300069':
            return DQN_select_1300069(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection,0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300044':
            return DQN_select_1300044(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection,0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300101':
            return DQN_select_1300101(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection,0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300046':
            return DQN_select_1300046(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300103':
            return DQN_select_1300103(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300870':
            return DQN_select_1300870(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection,0, cur_flow_pre_map, cur_queue_pre_map,overflowMap)

        elif cross_id == '1700086':
            return DQN_select_1700086(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1700275':
            return DQN_select_1700275(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1700276':
            return DQN_select_1700276(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1700124':
            return DQN_select_1700124(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1700125':
            return DQN_select_1700125(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300153':
            return DQN_select_1300153(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)



        elif cross_id == '1300166':
            return DQN_select_1300166(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300306':
            return DQN_select_1300306(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300409':
            return DQN_select_1300409(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1300362':
            return DQN_select_1300362(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1300087':
            return DQN_select_1300087(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1300147':
            return DQN_select_1300147(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)



        elif cross_id == '1700126':
            return DQN_select_1700126(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1700079':
            return DQN_select_1700079(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1300229':

            return DQN_select_1300229(traffic_vector, queue_vector, traffic_vector_duration2, current_time,

                                      flow_map_single_intersection, queue_map_single_intersection,

                                      stage_map_single_intersection, extend_map_single_intersection, 0,
                                      cur_flow_pre_map, cur_queue_pre_map)





        elif cross_id == '1300239':

            return DQN_select_1300239(traffic_vector, queue_vector, traffic_vector_duration2, current_time,

                                      flow_map_single_intersection, queue_map_single_intersection,

                                      stage_map_single_intersection, extend_map_single_intersection, 0,
                                      cur_flow_pre_map, cur_queue_pre_map)


        elif cross_id == '2702736':
            return DQN_select_2702736(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1700087':
            return DQN_select_1700087(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1700262':
            return DQN_select_1700262(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1700085':
            return DQN_select_1700085(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1700067':
            return DQN_select_1700067(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1700293':
            return DQN_select_1700293(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection,extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)





        elif cross_id == '1300271':
            return DQN_select_1300271(traffic_vector, queue_vector,traffic_vector_duration2,current_time,
               flow_map_single_intersection,queue_map_single_intersection,
               stage_map_single_intersection,last_coordinate_set,cur_flow_pre_map,
               cur_queue_pre_map,extend_map_single_intersection,
               overflowMap,radarMap_single_intersection,cross_id)

        elif cross_id == '1300086':
            return DQN_select_1300086(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300364':
            return DQN_select_1300364(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300253':
            return DQN_select_1300253(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300179':
            return DQN_select_1300179(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300094':
            return DQN_select_1300094(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300255':
            return DQN_select_1300255(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300039':
            return DQN_select_1300039(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300108':
            return DQN_select_1300108(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300266':
            return DQN_select_1300266(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300120':
            return DQN_select_1300120(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300230':
            return DQN_select_1300230(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)

        elif cross_id == '1300089':
            return DQN_select_1300089(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300358':
            return DQN_select_1300358(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300067':
            return DQN_select_1300067(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
        elif cross_id == '1300070':
            return DQN_select_1300070(traffic_vector, queue_vector, traffic_vector_duration2, current_time,
                                  flow_map_single_intersection, queue_map_single_intersection,
                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)
    else:
        sch = [0] * 10
    # if cross_id in Cross_Radar:
    #     if cross_id == '1300271':
    #         return DQN_select_1300271(traffic_vector, queue_vector,traffic_vector_duration2,current_time,
    #            flow_map_single_intersection,queue_map_single_intersection,
    #            stage_map_single_intersection,last_coordinate_set,cur_flow_pre_map,
    #            cur_queue_pre_map,extend_map_single_intersection,
    #            overflowMap,radarMap_single_intersection,cross_id)

    return sch,coordinate_map,model_info_list,EXP_list

def DQN_select_1300271(traffic_vector, queue_vector,traffic_vector_duration2,current_time,
               flow_map_single_intersection,queue_map_single_intersection,
               stage_map_single_intersection,last_coordinate_set,cur_flow_pre_map,
               cur_queue_pre_map,extend_map_single_intersection,
               overflowMap,radarMap_single_intersection,cross_id):
    Sub_UD = 5
    Sub_L  = 5
    Sub_R  = 5
    device_no = {
        'radar-ximenzi-333-01': "D",
        'radar-ximenzi-333-02': "R",
        'radar-ximenzi-333-03': "U",
        'radar-ximenzi-333-04': "L"
    }

    last = 0
    vector = {
        'D': [0] * 10,
        'L': [0] * 10,
        'U': [0] * 10,
        'R': [0] * 10,
    }
    if max(vector['R'])==0:
        Sub_R =0
    if max(vector['L'])==0:
        Sub_L =0
    if max(vector['U'])==0 and max(vector['D'])==0:
        Sub_UD = 0
    print("----------------------------------------"+"1300271")
    for radar in radarMap_single_intersection:
        try:
            radar_data = radarMap_single_intersection[radar]
            for pass_car_info in radar_data:
                lane = pass_car_info["laneNo"]
                device_ID = pass_car_info['deviceNo']
                if device_ID in device_no:
                    Turn = device_no[device_ID]
                    vector[Turn][lane] += 1
        except:
            continue
    ll = max(vector['L'][6:])
    rr = vector['R'][3]
    ud = max(max(vector['U'][2:5]), max(vector['D'][2:5]))
    udl = max((vector['U'][5]), (vector['D'][5]))
    schedule = Get_time_map(1300271)
    t = time.localtime(current_time)
    sch = schedule[str(t[3])]


    if ud < 34:
        ud = 38
    elif ud < 100:
        ud = 38 + 0.27 * (ud - 34)
    else:
        ud = 62

    sch[0] = Define_road_pass((ud +sch[0])/2,68,38,sch[0]+10,sch[0]-Sub_UD)

    if udl < 10:
        udl = 26
    elif udl < 58:
        udl = 26 + (udl - 10) * 0.4
    else:
        udl = 45 + 5

    sch[1] = Define_road_pass((udl +sch[1])/2,50,24,sch[1]+10,sch[1]-Sub_UD)
    if rr < 11:
        rr = 33
    elif rr < 76:
        rr = 33 + (rr - 11) * 0.18
    else:
        rr = 45 + 5
    sch[2] = Define_road_pass((rr +sch[2])/2,50,33,sch[2]+10,sch[2]-Sub_R)
    if ll < 34:
        ll = 33
    elif ll < 102:
        ll =33 + (ll - 34) * 0.25
    else:
        ll = 50+5
    sch[3] = Define_road_pass((ll +sch[3])/2,55,33,sch[3]+10,sch[3]-Sub_L)
    if 'overflow_U1' in overflowMap and sch[9]==0 :
        if overflowMap['overflow_U1']['state']==1 :
            sch[9] = 10
            sch[4] = int(sch[3])
            sch[3] = int(sch[2])
            sch[2] = int(sch[1])
            sch[1] = int(15 + sch[0] * 0.05)
            sch[0] = max(sch[0] - 15, 38)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {}
    return sch,coordinate_set,model_map,EXP_map


def DQN_select_1300068(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300068)
    stage = Stage_signal_ans1(1,2,3,0,0,0,0,0,0,3,stage_map_single_intersection)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300068])
    if stage[0]!=0:
        L,R,LL,RL,N,S = Get_pass_1368(stage,flow_map_single_intersection)
        pr = [L,R,LL,RL,N,S, 1300068]
        print(pr)
        sch[0] = Ng(sch[0]+max(L,R),2,min(76, sch[0] + 10), max(42, sch[0] - SUB_LR))
        sch[1] = Ng(sch[1]+max(LL,RL)+max(queue_vector['L'][1],queue_vector['R'][1])*1.7+13,3,min(35, sch[1] + 10), max(16, sch[1] - SUB_LR))
        sch[2] = Ng(sch[2]+max(N,S),2,min(55, sch[2] + 10), max(44, sch[2] - SUB_NS))
        if R - L > 13 and SUB_LR==5:
            sch[3] = int(sch[2])
            sch[2] = int(sch[1])
            sch[1] = 15
            sch[9] = 1
            if L < sch[0]:
                sch[0] = max(sch[0] - min(sch[0] - L, 5), 40)
    coordinate_set = {"s1":stage[0],"s2":stage[3]}
    print([sch[0], sch[1], sch[2], sch[3], 1300068])
    # if (traffic_vector_duration2[0]+traffic_vector_duration2[1]+traffic_vector_duration2[2]+traffic_vector_duration2[3])==0:
    sch=chuli_shuju("1300068",flow_map_single_intersection,extend_map_single_intersection)
    sch = select_pilot_schedule(
        "1300068",
        sch,
        flow_map_single_intersection,
        extend_map_single_intersection,
    )
    print("kjhxkjcshadkjsahdksad", sch)

    return sch,coordinate_set,model_map,EXP_map

def DQN_select_2712127(traffic_vector, queue_vector,traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    stage = Stage_signal_ans2(1, 2, 0, 0, 0, 0, 0, 0, 0, 2, stage_map_single_intersection)
    stage[8] = 2712127
    # print(stage)
    coordinate_map = {"s1": 0, "s2": 0}
    if stage[0]!=0:
        coordinate_map = {"s1":stage[0]-30,"s2":stage[2]-30}
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch=chuli_shuju("2712127",flow_map_single_intersection,extend_map_single_intersection)
    return sch,coordinate_map,model_map,EXP_map



def DQN_select_2703062(traffic_vector, queue_vector,traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(2703062)
    stage = Stage_signal_ans1(1, 5, 3, 0, 0, 0, 0, 0, 0, 3, stage_map_single_intersection)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 2703062])
    if stage[0] != 0:
        predict = predict_head(stage, flow_map_single_intersection, 3)
        print([predict[0], predict[1],predict[2], 2703062])
        sch[0] = Ng(sch[0] + predict[0], 2, min(55, sch[0] + 10), max(25, sch[0] - SUB_NS))
        sch[1] = Ng(sch[1] + predict[1] + queue_vector['U'][1] * 1.7 + 13, 3,min(35, sch[1] + 10), max(14, sch[1] - SUB_NS))
        sch[2] = Ng(sch[2] + predict[2], 2, min(55, sch[2] + 10), max(30, sch[2] - SUB_LR))
    print([sch[0], sch[1], sch[2], sch[3], 2703062])
    coordinate_set = {"s1": stage[0], "s2": stage[3]}
    sch=chuli_shuju("2703062",flow_map_single_intersection,extend_map_single_intersection)
    return sch,coordinate_set,model_map,EXP_map




def DQN_select_1300870(traffic_vector, queue_vector,traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map,overflowMap):
    SUB_NS = 10
    SUB_LR = 5
    print("-----------1300870------------")
    print(queue_map_single_intersection)
    print("-----------1300870-----------------")
    # print("1300870---------------------", flow_map_single_intersection)
    vector = {
        'D': [0] * 10,
        'L': [0] * 10,
        'U': [0] * 10,
        'R': [0] * 10,
    }

    for radar in flow_map_single_intersection:

        for i in range(len(flow_map_single_intersection[radar]['pass']['L'])):
            vector['L'][i] += flow_map_single_intersection[radar]['pass']['L'][i]
            vector['R'][i] += flow_map_single_intersection[radar]['pass']['R'][i]
            vector['U'][i] += flow_map_single_intersection[radar]['pass']['U'][i]
            vector['D'][i] += flow_map_single_intersection[radar]['pass']['D'][i]

    ul = vector['U'][5]
    d = max(vector['D'][2:])
    if traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2] == 0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    phase = [1, 2, 0, 0, 0, 0, 0, 0, 0, 0]
    schedule = Get_time_map(1300870)
    stage = Extend_singal_ans(phase, extend_map_single_intersection, 2)
    print("1300870", stage)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    # hour = '8'
    # sch = schedule[hour]
    print([sch[0], sch[1], sch[2], sch[3], 1300870])
    if stage[0] != 0:
        predict = predict_head(stage, flow_map_single_intersection, 2)
        print([predict[0], predict[1], predict[2], 1300870])
        sch[0] = Ng(sch[0] + predict[0], 2, min(80, sch[0] + 10), max(35, sch[0] - SUB_NS))
        sch[1] = Ng(sch[1] + predict[1], 2, min(50, sch[1] + 10), max(40, sch[1] - SUB_LR))
    today = date.today()

    minutes = t[3]*60 + t[4]

    if ul < 30:
        ul = 25
    elif ul < 70:
        ul = 25 + (ul - 30) * 0.11
    else:
        ul = 35
    ul = Define_road_pass(ul, 35, 20, 35, 0)

    if d < 25:
        d = 15
    elif d < 105:
        d = 15 + (d - 15) * 0.125
    else:
        d = 25
    d = Define_road_pass(d, 25, 15, 25, 15)



    print(ul,d)
    if ((minutes>= 7*60 and minutes<=9*60+30)or(minutes>= 17*60 +30and minutes<=19*60))and is_workday(today):
           sch[9] = 18
           sch[3] = 40
           sch[1] = int(sch[0] - 20)
           sch[0] = d
           sch[2] = (ul + 25) // 2
    print([sch[0], sch[1], sch[2], sch[3], 1300870])

    if 'overflow_U' in overflowMap and sch[9] == 0:
        if overflowMap['overflow_U']['distance'] < 50:
            sch[9] = 18
            sch[3] = 40
            sch[1] = max(min(int(sch[0] - 20),60),35)
            sch[0] = d+3
            sch[2] = (ul + 25) // 2
            if overflowMap['overflow_U']['distance'] < 0:
                sch[3] = 40
                sch[1] = max(min(int(sch[0] - 20),60),35)
                sch[0] = d + 6
                sch[2] = (ul + 25) // 2

    coordinate_set = {}


    return sch,coordinate_set,model_map,EXP_map


def DQN_select_1300106(traffic_vector, queue_vector,traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300106)
    stage = Stage_signal_ans1(2, 1, 3, 0, 0, 0, 0, 0, 0, 3, stage_map_single_intersection)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300106])
    sch[9]=1
    if stage[0] != 0:
        predict = predict_head(stage, flow_map_single_intersection, 3)
        print([predict[0], predict[1],predict[2], 1300106])

        sch[0] = Ng(sch[0] + predict[0], 2, min(60, sch[0] + 10), max(30, sch[0] - SUB_NS))
        sch[1] = Ng(sch[1] + predict[1] + max(queue_vector['L'][1], queue_vector['R'][1]) * 1.7 + 13, 3,min(35, sch[1] + 10), max(14, sch[1] - SUB_LR))
        sch[2] = Ng(sch[2] + predict[2], 2, min(50, sch[2] + 10), max(14, sch[2] - SUB_NS))
        coordinate_set = {"s1": stage[0]+10, "s2": stage[3]+10}
    else:
        coordinate_set = {"s1": 0, "s2": 0}
    print([sch[0], sch[1], sch[2], sch[3], 1300106])
    sch=chuli_shuju("1300106",flow_map_single_intersection,extend_map_single_intersection)
    return sch,coordinate_set,model_map,EXP_map


def DQN_select_1300047(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300047)
    stage = Stage_signal_ans2(8,4,0,0,0,0,0,0,0,2,stage_map_single_intersection)
    stage[8] = 1300047
    print(stage)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300047])
    if stage[0]!=0:
        predict = predict_head(stage, flow_map_single_intersection, 2)
        print([predict[0],predict[1],1300047])
        sch[0] = Ng(sch[0] + predict[0], 2, min(100,sch[0]+10), max(40,sch[0]-SUB_LR))
        sch[1] = Ng(sch[1] + predict[1], 2, min(55,sch[1]+10), max(40,sch[1]-SUB_NS))
    coordinate_set = {"s1":stage[0],"s2":stage[2]}
    print([sch[0], sch[1], sch[2], sch[3], 1300047])
    # if (traffic_vector_duration2[0]+traffic_vector_duration2[1]+traffic_vector_duration2[2]+traffic_vector_duration2[3])==0:

    # print("-----------------------------------------1300047------------------------------------")
    # print(flow_map_single_intersection, extend_map_single_intersection)
    # print("-----------------------------------------1300047-----------------------------------")
    # sch = reverse_time_from_three_cycle("1300047", flow_map_single_intersection, extend_map_single_intersection)
    #
    sch=chuli_shuju("1300047",flow_map_single_intersection,extend_map_single_intersection)
    # print("kjhxkjcshadkjsahdksad 1300047", sch)
    # if sch == None:
    #     sch = [0] * 10
    return sch,coordinate_set,model_map,EXP_map

def DQN_select_1300103(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300103)
    stage = Stage_signal_ans1(1,2,0,0,0,0,0,0,0,2,stage_map_single_intersection)
    stage[8] = 1300103
    print(stage)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300103])
    if stage[0]!=0:
        predict = predict_head(stage, flow_map_single_intersection, 1)
        print([predict[0], 1300103])
        sch[0] = Ng(sch[0] + predict[0], 2, min(70, sch[0] + 10), max(30, sch[0] - SUB_NS))
        sch[1] = int((sch[0]-30)*0.2)+20
    coordinate_set = {"Start1":0,"start2":0}
    print([sch[0], sch[1], sch[2], sch[3], 1300103])
    # if (traffic_vector_duration2[0]+traffic_vector_duration2[1]+traffic_vector_duration2[2]+traffic_vector_duration2[3])==0:
    return sch,coordinate_set,model_map,EXP_map

def DQN_select_1300092(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300092)
    stage = Stage_signal_ans2(8,4,0,0,0,0,0,0,0,2,stage_map_single_intersection)
    stage[8] = 1300092
    print(stage)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300092])
    if stage[0] != 0:
        predict = predict_head(stage, flow_map_single_intersection, 2)
        print([predict[0],predict[1],1300092])
        sch[0] = Ng(sch[0] + predict[1], 2, min(50, sch[0] + 10), max(25, sch[0] - SUB_NS))
        sch[1] = Ng(sch[1] + predict[0], 2, min(30, sch[1] + 10), max(20, sch[1] - SUB_LR))
    coordinate_set = {"s1":1,"s2":0}
    print([sch[0], sch[1], sch[2], sch[3], 1300092])
    # if (traffic_vector_duration2[0]+traffic_vector_duration2[1]+traffic_vector_duration2[2]+traffic_vector_duration2[3])==0:
    sch=chuli_shuju("1300092",flow_map_single_intersection,extend_map_single_intersection)
    return sch,coordinate_set,model_map,EXP_map


def DQN_select_1300069(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300069)
    stage = Stage_signal_ans1(1,2,3,4,0,0,0,0,0,4,stage_map_single_intersection)
    # print(stage)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300069])
    if stage[0]!=0:
        predict = predict_head(stage, flow_map_single_intersection, 4)
        print([predict[0],predict[1],predict[2],predict[3],1300069])
        sch[0] = Ng(sch[0] + predict[0], 2, min(60, sch[0] + 10), max(44, sch[0] - SUB_NS))
        sch[1] = Ng(sch[1] + predict[1] + max(queue_vector['U'][1], queue_vector['D'][1]) * 1.7 + 22, 3, min(35, sch[1] + 10), max(24, sch[1] - SUB_NS))
        sch[2] = Ng(sch[2] + predict[2], 2, min(70, sch[2] + 10), max(42, sch[2] - SUB_LR))
        sch[3] = Ng(sch[3] + predict[3] + max(queue_vector['L'][1], queue_vector['R'][1]) * 1.7 + 13, 3, min(30, sch[3] + 10), max(16, sch[3] - SUB_LR))

    coordinate_set = {"s1":stage[0],"s2":stage[4]}
    # print([sch[0], sch[1], sch[2], sch[3], 1300069])
    # # if (traffic_vector_duration2[0]+traffic_vector_duration2[1]+traffic_vector_duration2[2]+traffic_vector_duration2[3])==0:
    # sch = reverse_time_from_three_cycle("1300069", flow_map_single_intersection, extend_map_single_intersection)
    # print("kjhxkjcshadkjsahdksad 1300069", sch)
    sch=chuli_shuju("1300069",flow_map_single_intersection,extend_map_single_intersection)
    sch = select_pilot_schedule(
        "1300069",
        sch,
        flow_map_single_intersection,
        extend_map_single_intersection,
    )
    # if sch == None:
    #     sch = [0] * 10
    return sch,coordinate_set,model_map,EXP_map

def DQN_select_1300101(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if  traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300101)
    stage = Stage_signal_ans1(1,2,3,0,0,0,0,0,0,3,stage_map_single_intersection)
    stage[8] = 1300101
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300101])
    if stage[0]!=0:
        predict = predict_head(stage, flow_map_single_intersection, 3)
        print([predict[0], predict[1],predict[2], 1300101])
        sch[0] = Ng(sch[0] + predict[2], 2, min(55, sch[0] + 10), max(40, sch[0] - SUB_LR))
        sch[1] = Ng(sch[1] + predict[0], 2, min(70, sch[1] + 10), max(40, sch[1] - SUB_NS))
        sch[2] = Ng(sch[2] + predict[1] + max(queue_vector['U'][1], queue_vector['D'][1]) * 1.7 + 10, 3, min(35, sch[2] + 10), max(16, sch[2] - SUB_NS))
    coordinate_set = {"s1":stage[0],"s2":stage[3]}
    print([sch[0], sch[1], sch[2], sch[3], 1300101])
    # if (traffic_vector_duration2[0]+traffic_vector_duration2[1]+traffic_vector_duration2[2]+traffic_vector_duration2[3])==0:
    sch=chuli_shuju("1300101",flow_map_single_intersection,extend_map_single_intersection)

    return sch,coordinate_set,model_map,EXP_map

def DQN_select_1300097(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300097)
    stage = Stage_signal_ans1(1,2,0,0,0,0,0,0,0,2,stage_map_single_intersection)
    # print(stage)
    stage[8] = 1300097
    t = time.localtime(current_time)
    print(stage)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300097])
    coordinate_set = {"s1":0,"s2":0}
    if stage[0]!=0:
        predict = predict_head(stage, flow_map_single_intersection, 1)
        print([predict[0], 1300097])
        sch[0] = Ng(sch[0] + predict[0], 2, min(70, sch[0] + 10), max(40, sch[0] - SUB_NS))
        coordinate_set = {"s1":stage[0]+10,"s2":stage[2]+10}
    print([sch[0], sch[1], sch[2], sch[3], 1300097])
    # if (traffic_vector_duration2[0]+traffic_vector_duration2[1]+traffic_vector_duration2[2]+traffic_vector_duration2[3])==0:
    return sch,coordinate_set,model_map,EXP_map

def DQN_select_1300044(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300044)
    stage = Stage_signal_ans1(1, 2, 3, 0, 0, 0, 0, 0, 0, 3, stage_map_single_intersection)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300044])
    if stage[0] != 0:
        predict = predict_head(stage, flow_map_single_intersection, 3)
        print([predict[0],predict[1],predict[2], 1300044])
        sch[0] = Ng(sch[0] + predict[0] , 2, min(65,sch[0]+10), max(40,sch[0]-SUB_LR))
        sch[1] = Ng(sch[1] + predict[1], 2, min(65,sch[1]+10), max(40,sch[1]-SUB_NS))
        sch[2] = Ng(sch[2] + predict[2] + max(queue_vector['U'][1], queue_vector['D'][1]) * 1.7 + 17, 3, min(35,sch[2]+10), max(17,sch[2]-SUB_NS))
    print([sch[0], sch[1], sch[2], sch[3], 1300044])
    coordinate_set = {"Start1":1,"start2":0}

    # print("------------------------------")
    # sch = reverse_time_from_three_cycle("1300044", flow_map_single_intersection, extend_map_single_intersection)
    # print("kjhxkjcshadkjsahdksad 1300044", sch)
    #
    # if sch == None:
    #     sch = [0] * 10
    sch=chuli_shuju("1300044", flow_map_single_intersection, extend_map_single_intersection)
    return sch,coordinate_set,model_map,EXP_map

def DQN_select_1300046(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300046)
    stage = Stage_signal_ans2(8,4,9,0,0,0,0,0,0,3,stage_map_single_intersection)
    # print(stage)
    stage[8] = 1300046
    print(stage)
    t = time.localtime(current_time)
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300046])
    if stage[0]!=0:
        predict = predict_head(stage, flow_map_single_intersection, 1)
        print([predict[0], 1300046])
        sch[0] = Ng(sch[0] + predict[0], 2, min(70,sch[0]+10), max(40,sch[0]-SUB_LR))
        sch[1] = int((sch[0]-40)*0.2)+30
        sch[2] = int((sch[0]-40)*0.1)+30
    coordinate_set = {"s1":stage[0],"s2":stage[3]}
    print([sch[0], sch[1], sch[2], sch[3], 1300046])
    # if (traffic_vector_duration2[0]+traffic_vector_duration2[1]+traffic_vector_duration2[2]+traffic_vector_duration2[3])==0:

    return sch,coordinate_set,model_map,EXP_map


def DQN_select_1300042(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300042)
    stage = Stage_signal_ans2(8, 4, 0, 0, 0, 0, 0, 0, 0, 2, stage_map_single_intersection)
    stage[8] = 1300042
    t = time.localtime(current_time)
    sch = schedule[str(t[3])]
    print([sch[0],sch[1],sch[2], sch[3],1300042])
    coordinate_set = {"s1": 0, "s2": 0}
    if stage[0]!=0:
        predict = predict_head(stage, flow_map_single_intersection, 1)
        print([predict[0],1300042])
        sch[0] = Ng(sch[0] + predict[0], 2, min(70, sch[0] + 10), max(42, sch[0] - SUB_LR))
        coordinate_set = {"s1": stage[0], "s2": stage[2]}
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    # sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[2], sch[3], 1300042])
    sch=chuli_shuju("1300042",flow_map_single_intersection,extend_map_single_intersection)
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1300454(traffic_vector, queue_vector,traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0] == 0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2] == 0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300454)
    stage = Stage_signal_ans1(1, 2, 3, 0, 0, 0, 0, 0, 0, 3, stage_map_single_intersection)
    stage[8] = 1300454
    print(stage)
    t = time.localtime(current_time)
    sch = schedule[str(t[3])]
    print([sch[0], sch[1], sch[3], 1300454])
    coordinate_map = {"s1": 0, "s2": 0}
    ret = [0]*10
    if stage[0] != 0:
        L,R,LL,RL,N,S = Get_pass_13454(stage, flow_map_single_intersection)
        print([L, R, LL, RL, N, S, 1300454])
        if max(L,R)>60:
            if R-L>= 10:
                ret[0] = Ng(sch[0] + max(L, R), 2, min(60, sch[0] + 10), max(42, sch[0] - SUB_LR))
                ret[1] = int(min(max((R - L) * 1.5, 15), 30))
                ret[2] = Ng(sch[1] + max(LL, RL) + max(queue_vector['L'][1], queue_vector['R'][1]) * 1.5 + 14, 3,min(35, sch[1] + 10), max(16, sch[1] - SUB_LR))
                ret[3] = 12
                ret[4] = Ng(sch[3] + max(N, S), 2, min(60, sch[3] + 10), max(44, sch[3] - SUB_NS))
                ret[5] = 14
                ret[9] = 1
            elif L - R >= 10:
                ret[0] = Ng(sch[0] + max(L, R), 2, min(60, sch[0] + 10), max(42, sch[0] - SUB_LR))
                ret[1] = int(min(max((L - R) * 1.5, 15), 30))
                ret[2] = Ng(sch[1] + max(LL, RL) + max(queue_vector['L'][1], queue_vector['R'][1]) * 1.5 + 14, 3,min(35, sch[1] + 10), max(16, sch[1] - SUB_LR))
                ret[3] = 12
                ret[4] = Ng(sch[3] + max(N, S), 2, min(60, sch[3] + 10), max(44, sch[3] - SUB_NS))
                ret[5] = 14
                ret[9] = 3
            else:
                ret[0] = Ng(sch[0] + max(L, R)+6, 2, min(70, sch[0] + 10), max(42, sch[0] - SUB_LR))
                ret[1] = Ng(sch[1] + max(LL, RL) + max(queue_vector['L'][1], queue_vector['R'][1]) * 1.5 + 14, 3,min(35, sch[1] + 10), max(16, sch[1] - SUB_LR))
                ret[2] = 12
                ret[3] = Ng(sch[3] + max(N, S), 2, min(60, sch[3] + 10), max(44, sch[3] - SUB_NS))
                ret[4] = 14
                ret[9] = 2
        else:
            ret[0] = Ng(sch[0] + max(L, R)+4, 2, min(70, sch[0] + 10), max(42, sch[0] - SUB_LR))
            ret[1] = Ng(sch[1] + max(LL, RL) + max(queue_vector['L'][1], queue_vector['R'][1]) * 1.5 + 14, 3, min(35, sch[1] + 10), max(16, sch[1] - SUB_LR))
            ret[2] = 12
            ret[3] = Ng(sch[3] + max(N, S), 2, min(60, sch[3] + 10), max(44, sch[3] - SUB_NS))
            ret[4] = 14
            ret[9] = 2
    else:
        ret = sch


    coordinate_map = {"s1": stage[0], "s2": stage[1]}
    print([ret[0], ret[1], ret[2], ret[3], 1300454])
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    return ret,coordinate_map,model_map,EXP_map


def DQN_select_1300451(traffic_vector, queue_vector,traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    SUB_NS = 5
    SUB_LR = 5
    if traffic_vector_duration2[0]==0 or traffic_vector_duration2[1] == 0:
        SUB_LR = 0
    if traffic_vector_duration2[2]==0 or traffic_vector_duration2[3] == 0:
        SUB_NS = 0
    schedule = Get_time_map(1300451)
    stage = Stage_signal_ans1(1, 2, 3, 4, 0, 0, 0, 0, 0, 4, stage_map_single_intersection)
    stage[8] = 1300451
    print(stage)
    t = time.localtime(current_time)
    sch = schedule[str(t[3])]
    print([sch[0],sch[1],sch[2],sch[3],1300451])
    coordinate_map = {"s1": 0, "s2": 0}
    if stage[0] != 0:
        predict = predict_head(stage, flow_map_single_intersection,4)
        print([predict[0],predict[1],predict[2],predict[3], 1300451])
        sch[0] = Ng(sch[0] + predict[0], 2, min(70, sch[0] + 10), max(42, sch[0] - SUB_LR))
        sch[1] = Ng(sch[1] + predict[1] + max(queue_vector['L'][1], queue_vector['R'][1]) * 1.5 + 13, 3,min(30, sch[1] + 10), max(16, sch[1] - SUB_LR))
        sch[2] = Ng(sch[2] + predict[2], 2, min(60, sch[2] + 10), max(44, sch[2] - SUB_NS))
        sch[3] = Ng(sch[3] + predict[3] + max(queue_vector['U'][1], queue_vector['D'][1]) * 1.7 + 22, 3,min(35, sch[3] + 10), max(24, sch[3] - SUB_NS))
        coordinate_map = {"s1":stage[0],"s2":stage[1]}
    print([sch[0], sch[1], sch[2], sch[3], 1300451])
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    return sch,coordinate_map,model_map,EXP_map




def DQN_select_1700086(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700086-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700086-----------------------------------------------")

    sch=chuli_shuju3("1700086", flow_map_single_intersection)
    print("1700086____________________________________",sch,"1700086____________________________________")
    return sch,coordinate_set,model_map,EXP_map


def DQN_select_1700276(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700276-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700276-----------------------------------------------")

    sch=chuli_shuju3("1700276", flow_map_single_intersection)
    print("1700276____________________________________",sch,"1700276____________________________________")
    return sch,coordinate_set,model_map,EXP_map

def DQN_select_1700275(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700275-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700275-----------------------------------------------")

    sch=chuli_shuju3("1700275", flow_map_single_intersection)
    print("1700275____________________________________",sch,"1700275____________________________________")
    return sch,coordinate_set,model_map,EXP_map


def DQN_select_1700087(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700087-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700087-----------------------------------------------")

    sch=chuli_shuju("1700087", flow_map_single_intersection,extend_map_single_intersection)
    print("1700087____________________________________",sch,"1700087____________________________________")
    return sch,coordinate_set,model_map,EXP_map




def DQN_select_1300229(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1300229-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1300229-----------------------------------------------")

    sch=chuli_shuju("1300229", flow_map_single_intersection,extend_map_single_intersection)
    print("1300229____________________________________",sch,"1300229____________________________________")
    return sch,coordinate_set,model_map,EXP_map

def DQN_select_1300239(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1300239-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1300239-----------------------------------------------")

    sch=chuli_shuju("1300239", flow_map_single_intersection,extend_map_single_intersection)
    print("1300239____________________________________",sch,"1300239____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1700124(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700124-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700124-----------------------------------------------")

    sch=chuli_shuju("1700124", flow_map_single_intersection,extend_map_single_intersection)
    # print("1700124____________________________________",sch,"1700124____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1700125(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700125-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700125-----------------------------------------------")

    sch=chuli_shuju("1700125", flow_map_single_intersection,extend_map_single_intersection)
    sch = select_pilot_schedule(
        "1700125",
        sch,
        flow_map_single_intersection,
        extend_map_single_intersection,
    )
    # print("1700125____________________________________",sch,"1700125____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1700126(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700126-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700126-----------------------------------------------")

    sch=chuli_shuju("1700126", flow_map_single_intersection,extend_map_single_intersection)
    # print("1700126____________________________________",sch,"1700126____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1700079(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700079-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700079-----------------------------------------------")

    sch=chuli_shuju("1700079", flow_map_single_intersection,extend_map_single_intersection)
    # print("1700079____________________________________",sch,"1700079____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1300153(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1300153-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1300153-----------------------------------------------")

    sch=chuli_shuju("1300153", flow_map_single_intersection,extend_map_single_intersection)
    print("1300153____________________________________",sch,"1300153____________________________________")
    return sch,coordinate_set,model_map,EXP_map




def DQN_select_1300166(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1300166-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1300166-----------------------------------------------")

    sch=chuli_shuju("1300166", flow_map_single_intersection,extend_map_single_intersection)
    print("1300166____________________________________",sch,"1300166____________________________________")
    return sch,coordinate_set,model_map,EXP_map





def DQN_select_1300306(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1300306-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1300306-----------------------------------------------")

    sch=chuli_shuju("1300306", flow_map_single_intersection,extend_map_single_intersection)
    print("1300306____________________________________",sch,"1300306____________________________________")
    return sch,coordinate_set,model_map,EXP_map

#
def DQN_select_1300409(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1300409-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1300409-----------------------------------------------")

    sch=chuli_shuju("1300409", flow_map_single_intersection,extend_map_single_intersection)
    # print("1700079____________________________________",sch,"1700079____________________________________")
    return sch,coordinate_set,model_map,EXP_map


def DQN_select_1700262(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700262-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700262-----------------------------------------------")

    sch=chuli_shuju("1700262", flow_map_single_intersection,extend_map_single_intersection)
    # print("1700079____________________________________",sch,"1700079____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1700085(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700085-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700085-----------------------------------------------")

    sch=chuli_shuju("1700085", flow_map_single_intersection,extend_map_single_intersection)
    # print("1700079____________________________________",sch,"1700079____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1700067(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700067-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700067-----------------------------------------------")

    sch=chuli_shuju("1700067", flow_map_single_intersection,extend_map_single_intersection)
    # print("1700079____________________________________",sch,"1700079____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1700293(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1700293-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1700293-----------------------------------------------")

    sch=chuli_shuju("1700293", flow_map_single_intersection,extend_map_single_intersection)
    # print("1700079____________________________________",sch,"1700079____________________________________")
    return sch,coordinate_set,model_map,EXP_map




def DQN_select_1300362(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1300362-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1300362-----------------------------------------------")

    sch=chuli_shuju("1300362", flow_map_single_intersection,extend_map_single_intersection)
    print("1300362____________________________________",sch,"1300362____________________________________")
    return sch,coordinate_set,model_map,EXP_map





def DQN_select_1300087(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1300087-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1300087-----------------------------------------------")

    sch=chuli_shuju("1300087", flow_map_single_intersection,extend_map_single_intersection)
    print("1300087____________________________________",sch,"1300087____________________________________")
    return sch,coordinate_set,model_map,EXP_map

def DQN_select_1300147(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("1300147-----------------------------------------------")

    print(flow_map_single_intersection)

    print("1300147-----------------------------------------------")

    sch=chuli_shuju("1300147", flow_map_single_intersection,extend_map_single_intersection)
    print("1300147____________________________________",sch,"1300147____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_2702736(traffic_vector, queue_vector, traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)

    coordinate_set = {"Start1":1,"start2":0}
    print("2702736-----------------------------------------------")

    print(flow_map_single_intersection)

    print("2702736-----------------------------------------------")

    sch=chuli_shuju("2702736", flow_map_single_intersection,extend_map_single_intersection)
    print("2702736____________________________________",sch,"2702736____________________________________")
    return sch,coordinate_set,model_map,EXP_map



def DQN_select_1300086(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300086-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300086-----------------------------------------------")
    sch = chuli_shuju("1300086", flow_map_single_intersection, extend_map_single_intersection)
    print("1300086____________________________________", sch, "1300086____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300364(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300364-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300364-----------------------------------------------")
    sch = chuli_shuju("1300364", flow_map_single_intersection, extend_map_single_intersection)
    print("1300364____________________________________", sch, "1300364____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300253(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300253-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300253-----------------------------------------------")
    sch = chuli_shuju("1300253", flow_map_single_intersection, extend_map_single_intersection)
    print("1300253____________________________________", [0]*10, "1300253____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300179(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300179-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300179-----------------------------------------------")
    sch = chuli_shuju("1300179", flow_map_single_intersection, extend_map_single_intersection)
    print("1300179____________________________________", sch, "1300179____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300094(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300094-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300094-----------------------------------------------")
    sch = chuli_shuju("1300094", flow_map_single_intersection, extend_map_single_intersection)
    print("1300094____________________________________", sch, "1300094____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300255(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300255-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300255-----------------------------------------------")
    sch = chuli_shuju("1300255", flow_map_single_intersection, extend_map_single_intersection)
    print("1300255____________________________________", sch, "1300255____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300039(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300039-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300039-----------------------------------------------")
    sch = chuli_shuju("1300039", flow_map_single_intersection, extend_map_single_intersection)
    print("1300039____________________________________", sch, "1300039____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300108(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300108-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300108-----------------------------------------------")
    sch = chuli_shuju("1300108", flow_map_single_intersection, extend_map_single_intersection)
    print("1300108____________________________________", sch, "1300108____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300266(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300266-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300266-----------------------------------------------")
    sch = chuli_shuju("1300266", flow_map_single_intersection, extend_map_single_intersection)
    print("1300266____________________________________", sch, "1300266____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300120(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300120-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300120-----------------------------------------------")
    sch = chuli_shuju("1300120", flow_map_single_intersection, extend_map_single_intersection)
    print("1300120____________________________________", sch, "1300120____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300230(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300230-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300230-----------------------------------------------")
    sch = chuli_shuju("1300230", flow_map_single_intersection, extend_map_single_intersection)
    print("1300230____________________________________", sch, "1300230____________________________________")
    return sch, coordinate_set, model_map, EXP_map





def DQN_select_1300089(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300089-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300089-----------------------------------------------")
    sch = chuli_shuju("1300089", flow_map_single_intersection, extend_map_single_intersection)
    print("1300089____________________________________", sch, "1300089____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300358(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300358-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300358-----------------------------------------------")
    sch = chuli_shuju("1300358", flow_map_single_intersection, extend_map_single_intersection)
    print("1300358____________________________________", sch, "1300358____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300067(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300067-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300067-----------------------------------------------")
    sch = chuli_shuju("1300067", flow_map_single_intersection, extend_map_single_intersection)
    print("1300067____________________________________", sch, "1300067____________________________________")
    return sch, coordinate_set, model_map, EXP_map


def DQN_select_1300070(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map_single_intersection, queue_map_single_intersection, stage_map_single_intersection, extend_map_single_intersection, coordinate_map_set, cur_flow_pre_map, cur_queue_pre_map):
    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)
    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)
    coordinate_set = {"Start1": 1, "start2": 0}
    print("1300070-----------------------------------------------")
    print(flow_map_single_intersection)
    print("1300070-----------------------------------------------")
    sch = chuli_shuju("1300070", flow_map_single_intersection, extend_map_single_intersection)
    sch = select_pilot_schedule(
        "1300070",
        sch,
        flow_map_single_intersection,
        extend_map_single_intersection,
    )
    print("1300070____________________________________", sch, "1300070____________________________________")



    return sch, coordinate_set, model_map, EXP_map
