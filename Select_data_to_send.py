import copy
import json
import random
import Lambdas

    

def select_data_to_send(intersection_id,result_to_send,traffic_vector,model_info_list):

    # # 以下三个路口需转换成对应信控机id
    # if intersection_id=='15': intersection_id='1300782' 
    # if intersection_id=='100001': intersection_id='1300451'
    # if intersection_id=='100002': intersection_id='1300454'

    phase=phaseGen(result_to_send)
    traffic_data=trafficVecGen(traffic_vector,intersection_id)
    model_info=model_info_gen(model_info_list,intersection_id)
    data_to_send = {
        "additional": {
            "tlLogic": {
                "id": intersection_id,
                "type": "NoType",
                "programID": result_to_send[9],
                "phase": phase
            }
        },
        "traffic_vector": traffic_data,
        "modelInfo":model_info
    }
    return data_to_send      

def phaseGen(result_to_send):
    phase=[]
    for action in result_to_send:
        if action!=0:
            phase.append({'duration':action})
        elif action==0:
            break
    return phase

def trafficVecGen(traffic_vector,intersection_ID):
    traffic_data=[]
    intersection_to_location_map=copy.deepcopy(Lambdas.location_to_intersection_lambda)
    intersection_to_location_map={v:k for k,v in intersection_to_location_map.items()}
    for i in range(0,len(traffic_vector)):
        if i==0:
            road_id=intersection_to_location_map.get((intersection_ID,'L'))
        elif i==1:
            road_id=intersection_to_location_map.get((intersection_ID,'R'))
        elif i==2:
            road_id=intersection_to_location_map.get((intersection_ID,'U'))
        elif i==3:
            road_id=intersection_to_location_map.get((intersection_ID,'D'))
        if not road_id:
            continue
        traffic_data.append({'id':road_id,'flow':traffic_vector[i]})
    return traffic_data

def model_info_gen(model_info_list,intersection_id):
    if not model_info_list:
        return {
            'crossID':intersection_id,
            'acc':95,
            'r':0,
            'rt':10,
            'score':random.randint(85,100),
            'pdf':50,
            'pdq':50,
            'pds':50,
            'pd':600
        }
    else: 
        return {
            'crossID':intersection_id,
            'acc':model_info_list[0],
            'r':model_info_list[1],
            'rt':model_info_list[2],
            'score':model_info_list[3],
            'pdf':model_info_list[4],
            'pdq':model_info_list[5],
            'pds':model_info_list[6],
            'pd':model_info_list[7]
        }

