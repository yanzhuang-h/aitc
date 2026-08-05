import collections
from datetime import datetime, timedelta
import json
import Lambdas
import copy
import logging
# 设置日志记录器
logger = logging.getLogger("ProcessCacheData")
# 设置日志级别
def process_flow_data(cache):
    """
    处理600秒缓存内的所有流量数据，更新对应路口的流量统计。
    :param flow_data_list: 流量数据列表，每个元素包含 'jtll_ddbh' 和其他字段。
    :return: 更新后的四个路口的二维流量统计数组。
    """
    flow_map=copy.deepcopy(Lambdas.map_lambda)
    logger.info("Processing flow data...")
    
    location_to_intersection = Lambdas.location_to_intersection_lambda
    # 重置流量统计 顺序LRUD
    intersection_flow = copy.deepcopy(Lambdas.intersection_flow_lambda)


    try:
        for flow_data in cache:
            ddbh = int(flow_data["jtll_ddbh"])  # 地点编号
            cdbh = int(flow_data["ycsb_cdbh"])  #车道编号
            start_time_second=str(int(flow_data["ts"])//1000)
            # 获取路口编号和方向
            mapping = location_to_intersection.get(ddbh)
            if mapping is None:
                # print(f"Flow data processing warning:Unknown location ID: {ddbh}")
                continue

            intersection_id, direction = mapping
            if Lambdas.aibi_to_xinkongji.__contains__(intersection_id):
                intersection_id=Lambdas.aibi_to_xinkongji.get(intersection_id)
            if intersection_id not in flow_map:
                # print(f"Flow data processing warning:Unknown intersection ID: {intersection_id}")
                continue
            if start_time_second not in flow_map[intersection_id]:
                flow_map[intersection_id][start_time_second] = copy.deepcopy(Lambdas.flow_map_single_intersection_lambda)
            
            flow_map[intersection_id][start_time_second]["pass"][direction][cdbh]+=1
            flow_map[intersection_id][start_time_second]["count"][direction]+=1

            if direction == "L":
                intersection_flow[intersection_id][0] += 1
            elif direction == "R":
                intersection_flow[intersection_id][1] += 1
            elif direction == "U":
                intersection_flow[intersection_id][2] += 1
            elif direction == "D":
                intersection_flow[intersection_id][3] += 1
            else:
                print(f"Unknown direction: {direction}")
    except KeyError as e:
        logger.error(f"Missing key in flow data: {e}")
    except Exception as e:
        logger.error(f"Error processing flow data: {e}")
    # 返回最终的二维流量统计数组

    return intersection_flow,flow_map

def process_queue_data(cache):
    logger.info("Processing queue data...")
    queue_map=copy.deepcopy(Lambdas.map_lambda)


    # 用于保存4个路口每个道路每个车道的最大排队长度
    max_queue_lengths = copy.deepcopy(Lambdas.max_lengths_lambda)
    max_all_nums = copy.deepcopy(Lambdas.max_lengths_lambda)
    location_to_intersection = Lambdas.location_to_intersection_lambda
    valid_data_count=0
    # 遍历所有的排队数据
    for data in cache:
        try:
            
            # 确保数据是一个字典，如果是字符串，则先解析为字典
            if isinstance(data, str):
                item_data = json.loads(data)
            elif isinstance(data, dict):
                item_data = data
            else:
                continue
            
            # 解析排队数据
            ddbh = int(item_data.get("jtll_ddbh"))
            start_time_second=str(int(item_data.get("start_time"))//1000)
            if ddbh not in location_to_intersection:
                continue  # 跳过未知方向的数据
            valid_data_count+=1
            intersection_id,direction=location_to_intersection.get(ddbh)
            if Lambdas.aibi_to_xinkongji.__contains__(intersection_id):
                intersection_id=Lambdas.aibi_to_xinkongji.get(intersection_id)
            car_nums = item_data.get("car_nums")
            if not isinstance(car_nums, list):
                continue  # 如果 car_nums 不是列表，跳过

            for queue_data in car_nums:
                # 获取每个车道的排队数据
                ycsb_cdbh = queue_data.get("ycsb_cdbh")
                queue_length = queue_data.get("queue")
                all_nums=queue_data.get("all")
                # 确保 ycsb_cdbh 和 queue 存在，并且在合法范围内
                if ycsb_cdbh is not None and queue_length is not None and all_nums is not None:
                    # 确保 ycsb_cdbh 是整数类型，并且在合法范围内
                    try:
                        ycsb_cdbh = int(ycsb_cdbh)  # 确保 ycsb_cdbh 为整数
                        if 0 <= ycsb_cdbh < 7:
                            max_queue_lengths[intersection_id][direction][ycsb_cdbh] = max(max_queue_lengths[intersection_id][direction][ycsb_cdbh], queue_length)
                            max_all_nums[intersection_id][direction][ycsb_cdbh]=max(max_all_nums[intersection_id][direction][ycsb_cdbh],all_nums)
                            if start_time_second not in queue_map[intersection_id]:
                                queue_map[intersection_id][start_time_second] = copy.deepcopy(Lambdas.queue_map_single_intersection_lambda)
                            queue_map[intersection_id][start_time_second]["queue"][direction][ycsb_cdbh]=queue_length
                            queue_map[intersection_id][start_time_second]["all"][direction][ycsb_cdbh]=all_nums
                    except ValueError:
                        logger.warning(f"Invalid ycsb_cdbh value: {ycsb_cdbh} in data: {data}")
                        continue

        except json.JSONDecodeError:
            continue  # 如果 JSON 解析出错，跳过该条数据
        except KeyError as e:
            logger.error(f"Error processing queue data: Missing expected key {e}")
        except Exception as e:
            logger.error(f"Error processing queue data: {e}")
    print(f"{valid_data_count} queue data processed")
    return max_queue_lengths,queue_map

def process_stage_data(cache):
    logger.info("Processing stage data...")
    stage_map=copy.deepcopy(Lambdas.map_lambda)

    try:
        for stage_data in cache:
    
            IntersectionID=stage_data.get('CrossId')
            if Lambdas.aibi_to_xinkongji.__contains__(IntersectionID):
                IntersectionID=Lambdas.aibi_to_xinkongji.get(IntersectionID)
            if not stage_map.__contains__(IntersectionID):
                continue
            start_time_second=(int(stage_data.get("time"))//1000)
            curStageNo=int(stage_data.get("curStageNo"))
            curStageLen=int(stage_data.get("curStageLen"))
            if start_time_second not in stage_map[IntersectionID]:
                stage_map[IntersectionID][start_time_second] = copy.deepcopy(Lambdas.stage_map_lambda)
            stage_map[IntersectionID][start_time_second]['curStageNo']=curStageNo
            stage_map[IntersectionID][start_time_second]['curStageLen']=curStageLen
    except KeyError as e:
        logger.error(f"Missing key in stage data:{e}")
    except Exception as e:
        logger.error(f"Error processing stage data: {e}")
    
    return stage_map

def process_extend_data(cache):
    logger.info("Processing extend data...")
    extend_map = copy.deepcopy(Lambdas.map_lambda)
    try:
        for extend_data in cache:
            if len(extend_data) != 2 or not isinstance(extend_data[1], dict):
                print(f"Skipped invalid data type: {type(extend_data)}")
                continue
            intersection_id = extend_data[1].get('CrossId')
            if Lambdas.aibi_to_xinkongji.__contains__(intersection_id):
                intersection_id = Lambdas.aibi_to_xinkongji.get(intersection_id)
            if not extend_map.__contains__(intersection_id):
                continue
            start_time_sec = extend_data[0]
            extend_map[intersection_id].setdefault(start_time_sec, []).append(extend_data[1])
    except KeyError as e:
        logger.error(f"Missing key in extend data: {e}")
    except Exception as e:
        logger.error(f"Error processing extend data: {e}")
    logger.info(f"extend data processed:{extend_map}")
    return extend_map

def parse_timestamp(raw, divisor=1000):
    try:
        return int(float(raw)) // divisor
    except (TypeError, ValueError):
        return None

def process_online_data(cache):
    online_map = copy.deepcopy(Lambdas.online_data_map_lambda)

    for online_data in cache:
        if len(online_data) != 2 or not isinstance(online_data[1], dict):
            print(f"Skipped invalid data type: {type(online_data)}")
            continue
        
        
        raw_time,data_dict = online_data
        rid=data_dict.get('rid')
        
        if None in (rid, raw_time):
            print(f"Missing required fields in online data: {online_data}")
            continue
        
        start_time_sec = raw_time
        if start_time_sec is None:
            print(f"Invalid timestamp: {raw_time}")
            continue

        if rid not in online_map:
            print(f"Unregistered rid: {rid}")
            continue

        online_map[rid].setdefault(start_time_sec, []).append(data_dict)
    return online_map



def process_latest_data(cache):
    latest_map = copy.deepcopy(Lambdas.latest_data_map_lambda)
    
    for latest_data in cache:

        if len(latest_data) != 2 or not isinstance(latest_data[1], dict):
            print(f"Invalid latest data structure: {latest_data}")
            continue
        

        raw_time, data_dict = latest_data
        inter_id = data_dict.get('inter_id')
        start_time_sec = raw_time

        if None in (inter_id, start_time_sec):
            print(f"Missing required fields in latest data: {latest_data}")
            continue

        if inter_id not in latest_map:
            print(f"Unregistered inter_id: {inter_id}")
            continue

        latest_map[inter_id].setdefault(start_time_sec, []).append(data_dict)
    
    return latest_map

def process_radar_data(cache):
    """
    处理除事件数据以外的雷达数据，更新雷达事件map。
    """
    radarMap = copy.deepcopy(Lambdas.map_lambda)
    
    for cache_data in cache:
        if len(cache_data) != 2 or not isinstance(cache_data[1], dict):
            logger.warning(f"process radar data:Invalid radar data structure: {cache_data}")
            continue
        ts, radar_data = cache_data
        deviceNo = radar_data.get("deviceNo")
        if deviceNo is None:
            logger.warning("process radar data:Missing deviceNo in radar data.")
            continue
        if deviceNo not in Lambdas.device_to_location:
            logger.warning(f"process radar data:Device {deviceNo} not registered in device_to_location.")
            continue
        intersection_id, direction=Lambdas.device_to_location[deviceNo]
        if Lambdas.aibi_to_xinkongji.__contains__(intersection_id):
            intersection_id = Lambdas.aibi_to_xinkongji.get(intersection_id)
        radarMap[intersection_id].setdefault(int(ts),[]).append(radar_data)
    # logger.info(f"Processed radar data: {radarMap}")
    return radarMap

def process_radar_event_data(eventmap,overflowWariningMap):
    overflowMap= copy.deepcopy(Lambdas.map_lambda)
    for event_type,map in eventmap.items():
        if event_type not in Lambdas.radar_event_list:
            logger.warning(f"process radar event data:Unknown event type {event_type}.")
            continue
        elif event_type == "OverFlow":
            overflowMap = process_overflow_events(map,overflowWariningMap)
    return overflowMap
            

def process_overflow_events(overflowEventMap,overflowWariningMap):
    overflowMap = copy.deepcopy(Lambdas.map_lambda)
    
    for devNo, overflow_data in overflowEventMap.items():
        if devNo not in Lambdas.device_to_location:
            logger.warning(f"process overflow event: Device {devNo} not registered in device_to_location.")
            continue
        intersection_id, direction=Lambdas.device_to_location[devNo]
        overflowMap.setdefault(intersection_id, {}).setdefault(f"overflow_{direction}", Lambdas.eventMap_Overflow_lambda)
        if overflowWariningMap[intersection_id].get(direction) is not None:
            overflowMap[intersection_id][f"overflow_{direction}"]['distance'] = overflowWariningMap[intersection_id][direction].get("distance")
        createtime = overflow_data.get("createTime")
        
        # 安全处理createTime
        if not createtime or str(createtime).strip() == '':
            logger.warning(f"process overflow event: Missing or empty createTime for device {devNo}. Setting state to '0'.")
            # 当createTime为空时，认为是过期事件，设置state为'0'
            overflowMap[intersection_id][f"overflow_{direction}"]["state"] = '0'
            overflowMap[intersection_id][f"overflow_{direction}"]["createTime"] = ""
            continue
        
        try:
            past_time = datetime.strptime(str(createtime), '%Y-%m-%d %H:%M:%S')
            now = datetime.now()
            
            if (now - past_time) > timedelta(minutes=10):
                overflowMap[intersection_id][f"overflow_{direction}"]["state"] = '0'
            else:
                overflowMap[intersection_id][f"overflow_{direction}"]["state"] = '1'
                
            overflowMap[intersection_id][f"overflow_{direction}"]["createTime"] = str(createtime)
            
        except ValueError as e:
            logger.error(f"process overflow event: Invalid createTime format '{createtime}' for device {devNo}: {e}. Setting state to '0'.")
            overflowMap[intersection_id][f"overflow_{direction}"]["state"] = '0'
            overflowMap[intersection_id][f"overflow_{direction}"]["createTime"] = str(createtime) if createtime else ""
            
        except Exception as e:
            logger.error(f"process overflow event: Unexpected error processing device {devNo}: {e}. Setting state to '0'.")
            overflowMap[intersection_id][f"overflow_{direction}"]["state"] = '0'
            overflowMap[intersection_id][f"overflow_{direction}"]["createTime"] = str(createtime) if createtime else ""
    logger.info(f"Processed overflow events: {overflowMap}")
    
    for intersection_id,directionMap in overflowWariningMap.items():
        if directionMap is None:
            continue
        for direction,warningData in directionMap.items():
            if warningData is None:
                continue
            if overflowMap[intersection_id].get(f"overflow_{direction}") is None:
                overflowMap[intersection_id][f"overflow_{direction}"] = Lambdas.eventMap_Overflow_lambda.copy()
            overflowMap[intersection_id][f"overflow_{direction}"]['distance'] = warningData.get("distance")
            ts=warningData.get("ts")
            if ts is not None:
                overflowMap[intersection_id][f"overflow_{direction}"]['createTime'] = str(int(ts)//1000)
    logger.info(f"Final overflow map after merging warnings: {overflowMap}")
    return overflowMap       

def process_boyan_data(cache):
    boyan_map = copy.deepcopy(Lambdas.map_lambda)
    for data in cache:
        if len(data) != 2 or not isinstance(data[1], dict):
            logger.warning(f"process boyan data:Invalid boyan data structure: {data}")
            continue
        ts, boyan_data = data
        deviceId = boyan_data.get("deviceId")
        if deviceId is None:
            logger.warning("process boyan data:Missing deviceId in boyan data.")
            continue
        if deviceId not in Lambdas.boyan_device_to_location:
            logger.warning(f"process boyan data:Device {deviceId} not registered in boyan_device_to_location.")
            continue
        intersection_id, direction=Lambdas.boyan_device_to_location[deviceId]
        if Lambdas.aibi_to_xinkongji.__contains__(intersection_id):
            intersection_id = Lambdas.aibi_to_xinkongji.get(intersection_id)
        boyan_map[intersection_id].setdefault(direction, {})
        boyan_map[intersection_id][direction].setdefault(int(ts),[]).append(boyan_data)
    return boyan_map