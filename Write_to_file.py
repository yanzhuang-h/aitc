import datetime
import json
import os
import threading
import time
import logging
import json
import os
import threading
import time
import logging
# 设置日志记录
logger = logging.getLogger("Write_to_file")


file_lock=threading.Lock()
LOG_FILE_NAME={ # 日志类别键
    'flow' : None,
    'queue' : None,
    'heartbeat' : None,
    'history' : None,
    'action' : None,
    'send' : None,
    'stage' : None,
    'online': None,
    'flow_pre':None,
    'queue_pre':None,
    'debug':None,
    'schedule':None,
    'extend':None,
    'phase_check':None,
    'radar': None,
    'overflowWarning': None,
    'boyan': None
}
LOG_DIR = "logs_data"
EXP_LOG_DIR= os.path.join(LOG_DIR, "EXP")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(EXP_LOG_DIR, exist_ok=True)
current_date=None

# 极简字段表：可扩展，现只含时间戳
FIELD_DEFINITIONS = {
    "AITC_SYS_TS": lambda: int(time.time()),  # 秒级时间戳（舍去小数部分）
    # "AITC_SYS_TS_MS": lambda: int(time.time() * 1000),  # 毫秒级时间戳
    # 可继续添加其他字段
}

# 极简工具函数：将指定字段加入 data
def add_fields_to_data(data, fields):
    """
    data: dict 或 JSON 字符串
    fields: list[str]，要添加的字段名（从 FIELD_DEFINITIONS 查找）
    返回增强后的 dict
    
    使用示例：
        # data 为 dict
        augmented = add_fields_to_data({'a':1}, ['AITC_SYS_TS'])

        # data 为已序列化的 JSON 字符串
        augmented = add_fields_to_data(json.dumps({'a':1}), ['AITC_SYS_TS'])

    返回值说明：
        - 如果输入为 dict 或可解析的 JSON 字符串，返回一个 dict（包含新增字段）。
        - 如果输入是字符串且无法解析为 JSON，则原样返回该字符串（不修改）。
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return data  # 解析失败，原样返回
    result = data.copy() if isinstance(data, dict) else {}
    for field in fields:
        generator = FIELD_DEFINITIONS.get(field)
        if generator:
            try:
                result[field] = generator()
            except Exception:
                result[field] = None
    return result

# 用于重新设置LOG_FILE_NAME中每个类型对应的文件路径，按当天日期为文件名前缀
def update_file_name(directory=LOG_DIR):
    global current_date,LOG_FILE_NAME
    new_date=datetime.datetime.now().strftime("%Y-%m-%d")
    if new_date!=current_date:
        current_date=new_date
        for filetype in LOG_FILE_NAME.keys():
            directory=os.path.join(LOG_DIR, filetype)
            os.makedirs(directory, exist_ok=True)
            LOG_FILE_NAME[filetype]=os.path.join(directory,f"{current_date}_{filetype}.txt")

# 启动一个后台线程，每隔指定时间（默认1800秒）调用一次update_file_name函数
def start_filename_updater(interval=1800,directory=LOG_DIR):
    def updater():
        while True:
            update_file_name(directory)
            time.sleep(interval)
    thread=threading.Thread(target=updater,daemon=True)
    thread.start()

# 写入流量数据日志
def write_to_traffic_file(data):
    traffic_file_name=LOG_FILE_NAME['flow']
    # 在写入前添加 AITC_SYS_TS 字段
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    if isinstance(augmented, dict):
        text = json.dumps(augmented, ensure_ascii=False)
    else:
        text = augmented
    with file_lock:
        with open(traffic_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()
            
#写入排队数据日志
def write_to_queue_file(data):
    queue_file_name=LOG_FILE_NAME['queue']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(queue_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()

#写入stage数据日志
def write_to_stage_file(data):
    stage_file_name=LOG_FILE_NAME['stage']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(stage_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()

# 写入心跳数据日志
def write_to_heartbeat_file(data):
    heart_file_name=LOG_FILE_NAME["heartbeat"]
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(heart_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()

# 写入历史数据日志
def write_to_history_file(data):
    history_file_name=LOG_FILE_NAME['history']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(history_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()

# 写入发送数据日志
def write_to_send_file(data):
    send_file_name=LOG_FILE_NAME['send']
    # 在写入前添加 AITC_SYS_TS 字段
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    if isinstance(augmented, dict):
        text = json.dumps(augmented, ensure_ascii=False)
    else:
        text = augmented
    with file_lock:
        with open(send_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()

# 写入互联网数据日志
def write_to_online_file(data):
    online_file_name=LOG_FILE_NAME['online']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(online_file_name,'a', encoding='utf-8') as file:
            file.write(text+'\n')
            file.flush()    

# 写入流量预测文件日志
def write_to_flow_predict_file(data):
    flow_predict_file_name=LOG_FILE_NAME['flow_pre']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(flow_predict_file_name,'a', encoding='utf-8') as file:
            file.write(text+'\n')
            file.flush()

# 写入排队预测文件日志
def write_to_queue_predict_file(data):
    queue_predict_file_name=LOG_FILE_NAME['queue_pre']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(queue_predict_file_name,'a', encoding='utf-8') as file:
            file.write(text+'\n')
            file.flush()


# 写入schedule文件日志
def write_to_schedule_file(data):
    schedule_file_name=LOG_FILE_NAME['schedule']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(schedule_file_name,'a', encoding='utf-8') as file:
            file.write(text+'\n')
            file.flush()

# 
def gen_EXP_Json(EXP_list,intersection_id):
    EXP_LOG_DIR_INTERSECTION=os.path.join(EXP_LOG_DIR, intersection_id)
    os.makedirs(EXP_LOG_DIR_INTERSECTION, exist_ok=True)
    format_time = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")  
    EXP_FILE_NAME = f'EXP_{format_time}.json'
    file_path = os.path.join(EXP_LOG_DIR_INTERSECTION, EXP_FILE_NAME)
    # 将字典写入 JSON 文件
    EXP_map={'EXP':EXP_list}
    with open(file_path, 'w', encoding='utf-8') as json_file:
        json.dump(EXP_map, json_file, ensure_ascii=False, indent=4)

# 
def write_to_extend_file(data):
    # logger.info(f"Writing extend data: {data}")
    extend_file_name=LOG_FILE_NAME['extend']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(extend_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()

def write_to_phase_check_file(data):
    phase_check_file_name=LOG_FILE_NAME['phase_check']
    with file_lock:
        with open(phase_check_file_name, "a", encoding='utf-8') as file:
            file.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
            augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
            text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
            file.write(text + "\n")
            file.flush()
            
def write_to_radar_file(data):
    radar_file_name=LOG_FILE_NAME['radar']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(radar_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()
            
def write_to_overflowWarning_file(data):
    overflowWarning_file_name=LOG_FILE_NAME['overflowWarning']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(overflowWarning_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()
            
def write_to_boyan_file(data):
    boyan_file_name=LOG_FILE_NAME['boyan']
    augmented = add_fields_to_data(data, ["AITC_SYS_TS"])
    text = json.dumps(augmented, ensure_ascii=False) if isinstance(augmented, dict) else augmented
    with file_lock:
        with open(boyan_file_name, "a", encoding='utf-8') as file:
            file.write(text + "\n")
            file.flush()
            

