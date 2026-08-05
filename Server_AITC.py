import copy
import threading
import time
import json
import socket
import Flow_predict
import Queue_predict
# import torch
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor  # 用于线程池管理
from Select_data_to_send import select_data_to_send
import sys
import signal
import Process_cache_data
import Write_to_file
import Lambdas
import logging  # 添加日志模块
import logging.handlers  # 添加日志处理器
from phase_check import phase_check
from lib.DQN_Select import DQN_select
from lib.Global_intersection_coordinate import coordinate
from lib.nacos_floating_value import (
    NacosFloatingValueSync,
    NacosIntersectionResultConfigSync,
    NacosRoadStateSync,
    NacosTimeScheduleSync,
)
from lib.config_api import handle_config_request
from infra.data import DataKind, DataSource, RuntimeDataCache, RuntimeDataWriter, classify_data

# HTTP服务器相关导入
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.parse

# ================== 日志配置 ==================
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 创建文件处理器（按天切割日志）
    file_handler = logging.handlers.TimedRotatingFileHandler(
        'server.log', when='midnight', backupCount=7
    )
    file_handler.setLevel(logging.INFO)
    
    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

# 初始化日志
logger = setup_logging()
nacos_floating_value_sync = NacosFloatingValueSync()
nacos_intersection_result_sync = NacosIntersectionResultConfigSync()
nacos_road_state_sync = NacosRoadStateSync()
nacos_time_schedule_sync = NacosTimeScheduleSync()
# =============================================

processing_flag = False  # 标记是否正在处理一轮数据

# 缓存已加载的模块
loaded_dqn_modules = {}

#定义反溢警告map
overflowWarningMap=copy.deepcopy(Lambdas.map_lambda)

FLOW_WINDOW_DURATION = 600  # 窗口时长 600 秒
FLOW_WINDOW_DURATION2=150
SEND_INTERVAL = 50  # 发送数据的间隔

QUEUE_WINDOW_DURATION = 240  # 窗口时长 240 秒

STAGE_WINDOW_DURATION=600

EXTEND_WINDOW_DURATION = 600  # 窗口时长 600 秒

ONLINE_WINDOW_DURATION=1800

LATEST_WINDOW_DURATION=1800

RADAR_WINDOW_DURATION=600

BOYAN_WINDOW_DURATION=600

# 运行期窗口缓存，先保持旧系统各类数据窗口时长不变
runtime_data_cache = RuntimeDataCache({
    DataKind.FLOW: FLOW_WINDOW_DURATION,
    DataKind.QUEUE: QUEUE_WINDOW_DURATION,
    DataKind.STAGE: STAGE_WINDOW_DURATION,
    DataKind.EXTEND: EXTEND_WINDOW_DURATION,
    DataKind.ONLINE: ONLINE_WINDOW_DURATION,
    DataKind.LATEST: LATEST_WINDOW_DURATION,
    DataKind.RADAR: RADAR_WINDOW_DURATION,
    DataKind.BOYAN: BOYAN_WINDOW_DURATION,
})

# 雷达事件map
radar_event_map = {key:{}for key in Lambdas.radar_event_list}
global_overflow_warning={}
# 上一轮模型执行情况
last_coordinate_set=copy.deepcopy(Lambdas.map_lambda)

# 服务器配置

#HOST = '172.17.0.11'
# HOST = '11.82.117.80'
HOST = '127.0.0.1'

PORT = 65432
BUFFER_SIZE = 1024 * 1024

# HTTP雷达服务器配置

# RADAR_HTTP_HOST = '172.17.0.11'
RADAR_HTTP_HOST ='127.0.0.1'
# RADAR_HTTP_HOST ='11.82.117.80'


RADAR_HTTP_PORT = 8088

# 文件写入锁
file_lock = threading.Lock()
import_lock = threading.Lock()
# 用于存储所有活动线程和退出标志
client_threads = []
exit_flags = {}
# 创建一个线程池，限制最大线程数
executor = ThreadPoolExecutor(max_workers=20)

# 定义流量预测任务开始时间
pre_hour=3
pre_min=0

#定义用于测试的数据结构
traffic_count=0
LXD_stage_count=0

result_to_send_set=[]
clients = []              # 存储所有活跃客户端套接字
clients_lock = threading.Lock()  # 客户端列表的线程锁
result_lock = threading.Lock()   # 计算结果的线程锁
send_lock=threading.Lock()

# HTTP服务器关闭标志
http_server_shutdown = threading.Event()

Write_to_file.start_filename_updater()
runtime_data_writer = RuntimeDataWriter(Write_to_file)

CORS_RESPONSE_HEADERS = {
    "access-control-allow-origin",
    "access-control-allow-credentials",
    "access-control-allow-methods",
    "access-control-allow-headers",
    "access-control-expose-headers",
    "access-control-max-age",
}

SECURITY_RESPONSE_HEADERS = {
    "X-Permitted-Cross-Domain-Policies": "none",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": "max-age=16070400; includeSubDomains",
    "X-XSS-Protection": "1; mode=block",
    "X-Download-Options": "noopen",
}


def is_cross_origin_request(origin, host):
    if not origin:
        return False

    try:
        parsed_origin = urlparse(origin)
    except ValueError:
        return True

    origin_host = (parsed_origin.netloc or "").lower()
    request_host = (host or "").lower()
    return not origin_host or origin_host != request_host



# ================== HTTP雷达数据处理器 ==================
class RadarHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "AITCServer"
    sys_version = ""

    def send_header(self, keyword, value):
        if keyword.lower() in CORS_RESPONSE_HEADERS:
            return
        super().send_header(keyword, value)

    def end_headers(self):
        for header, value in SECURITY_RESPONSE_HEADERS.items():
            self.send_header(header, value)
        super().end_headers()

    def _reject_cross_origin_request(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if not is_cross_origin_request(origin, host):
            return False

        logger.warning(
            "Blocked cross-origin request: origin=%s host=%s path=%s",
            origin,
            host,
            self.path,
        )
        self.send_response(403)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = {"error": "Cross-origin requests are not allowed"}
        self.wfile.write(json.dumps(response).encode('utf-8'))
        return True

    def do_OPTIONS(self):
        if self._reject_cross_origin_request():
            return
        self.send_response(204)
        self.end_headers()

    def _send_json(self, status_code, payload):
        """发送 JSON 响应。"""
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _try_handle_config(self, method, body):
        """尝试按配置接口处理请求；处理成功返回 True。"""
        try:
            outcome = handle_config_request(method, urlparse(self.path).path, body)
        except Exception as e:
            logger.error(f"Error in config API handler: {e}", exc_info=True)
            self._send_json(500, {"status": "error", "reason": "internal server error"})
            return True

        if outcome is None:
            return False

        status_code, payload = outcome
        self._send_json(status_code, payload)
        return True

    def do_POST(self):
        if self._reject_cross_origin_request():
            return

        # 配置接口: /road_info/add|update, /cross_info/add|update
        parsed_path = urlparse(self.path).path
        if parsed_path.startswith(('/road_info', '/cross_info')):
            content_length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(content_length) if content_length else b''
            try:
                body = json.loads(raw.decode('utf-8')) if raw else None
            except json.JSONDecodeError as e:
                self._send_json(400, {"status": "error", "saved": False,
                                      "reason": f"Invalid JSON: {str(e)}"})
                return
            if self._try_handle_config('POST', body):
                return

        """处理POST请求，接收雷达数据"""
        try:
            # 获取请求体长度
            content_length = int(self.headers.get('Content-Length', 0))
            
            if content_length == 0:
                self.send_error(400, "Empty request body")
                return
            
            # 读取请求体
            post_data = self.rfile.read(content_length)
            
            # 解析JSON数据
            try:
                radar_data = json.loads(post_data.decode('utf-8'))
                
                # 处理雷达数据
                self.process_radar_data(radar_data)
                
                # 发送成功响应
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                
                response = {"status": "success", "message": "Radar data received"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error in radar HTTP handler: {e}")
                self.send_error(400, f"Invalid JSON: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error in radar HTTP handler: {e}", exc_info=True)
            self.send_error(500, f"Internal server error: {str(e)}")
    
    def do_GET(self):
        if self._reject_cross_origin_request():
            return

        # 配置接口: GET /road_info/{Cross_id}, GET /cross_info/{Cross_id}
        parsed_path = urlparse(self.path).path
        if parsed_path.startswith(('/road_info', '/cross_info')):
            if self._try_handle_config('GET', None):
                return

        """处理GET请求，可用于健康检查"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        response = {
            "status": "running", 
            "service": "radar_data_receiver",
            "radar_cache_size": runtime_data_cache.size(DataKind.RADAR)
        }
        self.wfile.write(json.dumps(response).encode('utf-8'))
    
    def process_radar_data(self, data):
        """处理雷达数据"""
        try:
            if isinstance(data, list):
                for item in data:
                    self.handle_single_radar_data(item)
            elif isinstance(data, dict):
                self.handle_single_radar_data(data)
            else:
                logger.warning("Unsupported radar data format")
        except Exception as e:
            logger.error(f"Error processing radar data: {e}", exc_info=True)
    
    def handle_single_radar_data(self, item):
        """处理单条雷达数据"""
        try:
            classified = classify_data(item, source=DataSource.HTTP)
            runtime_data_writer.write(classified.kind, item)

            if classified.kind in (DataKind.RADAR, DataKind.RADAR_EVENT):
                type_value = item.get("eventType")
                deviceNo = item.get("deviceNo")
                
                # 添加到雷达数据窗口
                if classified.kind == DataKind.RADAR and deviceNo in Lambdas.device_to_location:
                    add_to_radar_window(item)
                
                # 处理雷达事件
                if classified.kind == DataKind.RADAR_EVENT and type_value in Lambdas.radar_event_list and deviceNo in Lambdas.device_to_location:
                    radar_event_map[type_value][deviceNo] = item
                
                logger.debug(f"Processed radar data from device: {deviceNo}")
            elif classified.kind == DataKind.BOYAN:
                deviceId=item.get('deviceId')
                if deviceId in Lambdas.boyan_device_to_location:
                    add_to_boyan_window(item)
            else:
                logger.warning("Received non-radar data in radar HTTP handler")
        except Exception as e:
            logger.error(f"Error handling single radar data: {e}", exc_info=True)
            
    def log_message(self, format, *args):
        """重写日志方法，使用自定义logger"""
        logger.info(f"HTTP Radar Server: {format % args}")

def start_radar_http_server():
    """启动HTTP雷达数据接收服务器"""
    try:
        server = HTTPServer((RADAR_HTTP_HOST, RADAR_HTTP_PORT), RadarHTTPRequestHandler)
        logger.info(f"Radar HTTP server started on {RADAR_HTTP_HOST}:{RADAR_HTTP_PORT}")
        
        # 在单独线程中运行服务器
        def run_server():
            while not http_server_shutdown.is_set():
                try:
                    server.timeout = 1.0  # 设置超时，以便能够检查shutdown标志
                    server.handle_request()
                except Exception as e:
                    if not http_server_shutdown.is_set():
                        logger.error(f"Error in radar HTTP server: {e}")
        
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        
        return server, server_thread
    except Exception as e:
        logger.error(f"Failed to start radar HTTP server: {e}", exc_info=True)
        return None, None

# ================== 雷达相关函数 ==================
def add_to_radar_window(data):
    runtime_data_cache.add(DataKind.RADAR, data)
def add_to_boyan_window(data):
    runtime_data_cache.add(DataKind.BOYAN, data)
                   
def add_to_extend_window(data):
    runtime_data_cache.add(DataKind.EXTEND, data)

def add_to_latest_window(data):
    runtime_data_cache.add(DataKind.LATEST, data)

def add_to_online_window(data):
    runtime_data_cache.add(DataKind.ONLINE, data)
               
# 将数据添加到时间窗口缓存
def add_to_flow_window(data):
    runtime_data_cache.add(DataKind.FLOW, data)

def add_to_queue_window(data):
    runtime_data_cache.add(DataKind.QUEUE, data)

# 将数据添加到时间窗口缓存
def add_to_stage_window(data):
    runtime_data_cache.add(DataKind.STAGE, data)

# 主动清除cache中的过期数据
def clear_expired_data(kind=None):
    runtime_data_cache.clear_expired(kind)

def process_single_intersection(intersection_id, intersection_flow, result_queue_length,flow_map,queue_map,stage_map,intersection_flow_duration2,cur_flow_pre_map,cur_queue_pre_map,extend_map,online_map, overflowMap,radarMap,boyan_map):
    global last_coordinate_set
    current_time = time.time()
    intersection_result_map=copy.deepcopy(Lambdas.intersection_result_lambda)
    traffic_vector = intersection_flow[intersection_id]
    traffic_vector_duration2=intersection_flow_duration2[intersection_id]
    queue_vector = result_queue_length[intersection_id]
    flow_map_single_intersection=dict(flow_map[intersection_id])
    queue_map_single_intersection=dict(queue_map[intersection_id])
    stage_map_single_intersection=dict(stage_map[intersection_id])
    extend_map_single_intersection=dict(extend_map[intersection_id])
    radarMap_single_intersection=dict(radarMap[intersection_id])
    radar_event_map_single_intersection=dict(overflowMap[intersection_id])
    boyan_map_single_intersection=dict(boyan_map[intersection_id])
    logger.info(f"boyan_map_single_intersection for {intersection_id}: {boyan_map_single_intersection}")
    if cur_flow_pre_map : cur_flow_pre_map_single_intersection=cur_flow_pre_map.get(intersection_id)
    if cur_queue_pre_map: cur_queue_pre_map_single_intersection=cur_queue_pre_map.get(intersection_id)
    
    online_map_single_intersection=dict()
    if intersection_id in Lambdas.intersection_to_rid_lambda:
        for rid,direction in Lambdas.intersection_to_rid_lambda[intersection_id]:
            if rid in online_map:
                online_map_single_intersection[rid]=online_map[rid]
                
    
    try:

        result_action,coordinate_map,model_info_list,EXP_list= DQN_select(traffic_vector, queue_vector,traffic_vector_duration2,current_time,flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,last_coordinate_set,cur_flow_pre_map,cur_queue_pre_map,extend_map_single_intersection,radar_event_map_single_intersection,radarMap_single_intersection,intersection_id,boyan_map_single_intersection)
        Write_to_file.gen_EXP_Json(EXP_list,intersection_id)
        intersection_result_map['result_action']=result_action
        intersection_result_map['traffic_vector']=traffic_vector
        intersection_result_map['model_info_list']=model_info_list
        logger.info(f"Intersection: {intersection_id} process result : {intersection_result_map}")
    except Exception as e:
        logger.error(f'Error getting dqn_{intersection_id} result:{e}', exc_info=True)
    return intersection_id,intersection_result_map,coordinate_map

# 把流量数据和排队数据提交给模型处理
def process_data_to_send():
    global last_coordinate_set
    global radar_event_map
    global overflowWarningMap
    clear_expired_data(DataKind.FLOW)
    clear_expired_data(DataKind.QUEUE)
    clear_expired_data(DataKind.STAGE)
    clear_expired_data(DataKind.EXTEND)
    clear_expired_data(DataKind.BOYAN)
    recent_boyan_data=get_recent_boyan_data()
    recent_flow_data = get_recent_flow_data()
    recent_flow_data_duration2= get_duration_flow_data(FLOW_WINDOW_DURATION2)
    recent_queue_data = get_recent_queue_data()
    recent_stage_data = get_recent_stage_data()
    recent_extend_data = get_recent_extend_data()
    logger.info(f" extend_data_cache size: {runtime_data_cache.size(DataKind.EXTEND)}")  
    if not recent_flow_data:
        intersection_flow = copy.deepcopy(Lambdas.intersection_flow_lambda)
        intersection_flow_duration2=intersection_flow
        flow_map=copy.deepcopy(Lambdas.map_lambda)
    else:
        intersection_flow,flow_map = Process_cache_data.process_flow_data(recent_flow_data)
        intersection_flow_duration2,flow_map_duration2=Process_cache_data.process_flow_data(recent_flow_data_duration2)
        
        # 获取流量预测数据并存入文件
        end_time=recent_flow_data[0].get('ts')
        flow_predict_data=Flow_predict.flow_pre_json_Gen(intersection_flow,intersection_flow_duration2,end_time)
        Write_to_file.write_to_flow_predict_file(json.dumps(flow_predict_data))
    if not recent_queue_data:
        result_queue_length = copy.deepcopy(Lambdas.max_lengths_lambda)
        queue_map=copy.deepcopy(Lambdas.map_lambda)
    else:
        result_queue_length,queue_map = Process_cache_data.process_queue_data(recent_queue_data)

        # 获取排队预测数据并存入文件
        start_time=recent_queue_data[0].get("start_time")
        queue_pre_data=Queue_predict.queue_pre_json_gen(result_queue_length,start_time)
        Write_to_file.write_to_queue_predict_file(json.dumps(queue_pre_data))
    if not recent_stage_data:
        stage_map=copy.deepcopy(Lambdas.map_lambda)
    else:
        stage_map=Process_cache_data.process_stage_data(recent_stage_data)
    if not recent_extend_data:
        extend_map=copy.deepcopy(Lambdas.map_lambda)
    else:
        extend_map=Process_cache_data.process_extend_data(recent_extend_data)
    result_map=copy.deepcopy(Lambdas.map_lambda)
    if not recent_boyan_data:
        boyan_map=copy.deepcopy(Lambdas.map_lambda)
    else:
        boyan_map=Process_cache_data.process_boyan_data(recent_boyan_data)

    cur_flow_pre_map=Flow_predict.get_current_flow_prediction()

    #获取当前的排队预测map
    cur_queue_pre_map=Queue_predict.get_current_queue_prediction()

    #获取互联网数据map
    clear_expired_data(DataKind.ONLINE)
    online_data=get_recent_online_data()
    online_map=Process_cache_data.process_online_data(online_data)
    
    #获取radar数据
    clear_expired_data(DataKind.RADAR)
    radar_data=get_recent_radar_data()
    if not radar_data:
        radarMap=copy.deepcopy(Lambdas.map_lambda)
    else:
        radarMap=Process_cache_data.process_radar_data(radar_data)
    overflowMap=Process_cache_data.process_radar_event_data(radar_event_map,overflowWarningMap)
    global_overflow_warning=overflowMap
    with ThreadPoolExecutor(max_workers=30) as executor:
            future_to_intersection = {
                executor.submit(process_single_intersection, 
                                intersection_id,intersection_flow,result_queue_length,
                                flow_map,queue_map,stage_map,intersection_flow_duration2,
                                cur_flow_pre_map,cur_queue_pre_map,extend_map,online_map,
                                overflowMap,radarMap,boyan_map): intersection_id
                for intersection_id in Lambdas.intersection_list
            }
            new_coordinate_set=copy.deepcopy(Lambdas.map_lambda)
            for future in future_to_intersection:
                try:
                    intersection_id,result_future,map_future=future.result()
                    result_map[intersection_id]=result_future  # 获取每个路口的处理结果
                    new_coordinate_set[intersection_id]=map_future
                except Exception as e:
                    logger.error(f"Error processing intersection data: {e}", exc_info=True)
            last_coordinate_set=new_coordinate_set
    return result_map,online_map


# 获取时间窗口内的数据
def get_recent_flow_data():
    return runtime_data_cache.recent_data(DataKind.FLOW)

def get_recent_online_data():
    return runtime_data_cache.recent_legacy_tuples(DataKind.ONLINE)

def get_recent_latest_data():
    return runtime_data_cache.recent_legacy_tuples(DataKind.LATEST)

def get_duration_flow_data(duration):
    return runtime_data_cache.duration_data(DataKind.FLOW, duration)

def get_recent_queue_data():
    return runtime_data_cache.recent_data(DataKind.QUEUE)

def get_recent_stage_data():
    return runtime_data_cache.recent_data(DataKind.STAGE)

def get_recent_extend_data():
    return runtime_data_cache.recent_legacy_tuples(DataKind.EXTEND)
def get_recent_radar_data():
    return runtime_data_cache.recent_legacy_tuples(DataKind.RADAR)

def get_recent_boyan_data():
    return runtime_data_cache.recent_legacy_tuples(DataKind.BOYAN)

def periodic_data_processing():
    global processing_flag
    global result_to_send_set
    while True:
        start_time = time.time()
        # 如果正在处理中，等待前一次完成
        while processing_flag:
            time.sleep(0.1)
        
        processing_flag = True
        try:
            # 执行数据处理
            current_result,online_map = process_data_to_send()
            # print(f"current_result:{current_result}")
            # result_check_report=phase_check(current_result)
            # Write_to_file.write_to_phase_check_file(json.dumps(result_check_report))
            # 生成全局发送数据集
            action={}
            for intersection_id in current_result:
                action[intersection_id] = current_result[intersection_id]['result_action']
            if len(current_result)==len(Lambdas.intersection_list): 
                action=coordinate(action,last_coordinate_set,online_map,global_overflow_warning)
            action,result_check_report=phase_check(action)
            print(f"final action after coordinate floating value and phase_check:{action}")
            Write_to_file.write_to_phase_check_file(json.dumps(result_check_report))
            with send_lock:
                result_to_send_set=[]
                for intersection_id in  current_result:
                    current_result[intersection_id]['result_action']=action[intersection_id]
                    data_to_send = select_data_to_send(intersection_id, action[intersection_id],current_result[intersection_id]['traffic_vector'],current_result[intersection_id]['model_info_list'])
                    result_to_send_set.append(data_to_send)
        except Exception as e:
            logger.error(f"数据处理失败: {e}", exc_info=True)
        finally:
            processing_flag = False
            logger.info("最新结果已更新。。。。")
        # 动态等待剩余时间
        elapsed = time.time() - start_time
        wait_time = max(0, SEND_INTERVAL - elapsed)
        time.sleep(wait_time)

def broadcast_results():
    """独立线程：将最新结果广播给所有客户端"""
    global result_to_send_set
    while True:
        # 获取当前结果和客户端列表
        with clients_lock:
            current_clients = clients.copy()
        with send_lock:
            cur_send_set=result_to_send_set
        if cur_send_set==[]:
            time.sleep(1)
            continue

        # 向所有客户端发送数据
        for client_socket in current_clients:
            try:
                for result in cur_send_set:
                    client_socket.sendall(json.dumps(result).encode('utf-8'))
                    Write_to_file.write_to_send_file(result)
            except (socket.error, BrokenPipeError):
                # 客户端断开时清理
                with clients_lock:
                    if client_socket in clients:
                        clients.remove(client_socket)
                client_socket.close()
                logger.warning("客户端断开连接，已清理")
        logger.info(f'Send results to all Client:{current_clients}')
        # logger.info(cur_send_set)
        time.sleep(SEND_INTERVAL)

################# 数据流输入入口#############################
# 处理客户端连接
def handle_client(client_socket, address):
    logger.info(f"Connection from {address} established.")
    # 注册客户端
    with clients_lock:
        clients.append(client_socket)

    buffer = ""
    try:
        while True:
            data = client_socket.recv(BUFFER_SIZE).decode('utf-8')
            if not data:
                break
            buffer += data
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                try:
                    json_data = json.loads(line)
                    preprocess_data(json_data)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON Decode Error: {e}, Data: {line}")
    except Exception as e:
        logger.error(f"Error in handle_client: {e}", exc_info=True)
    finally:
        # 客户端断开时清理
        with clients_lock:
            if client_socket in clients:
                clients.remove(client_socket)
        client_socket.close()
        logger.info(f"Connection from {address} closed.")

def preprocess_data(data):
    """
    处理解析后的 JSON 数据。
    根据数据类型调用不同的处理逻辑。
    """
    try:
        if isinstance(data, list):
            for item in data:
                handle_individual_data(item)
        elif isinstance(data, dict):
            handle_individual_data(data)
        else:
            logger.warning("Unsupported data format.")
    except Exception as e:
        logger.error(f"Error processing data: {e}", exc_info=True)

def handle_individual_data(item):
    global traffic_count
    global LXD_stage_count
    """
    根据具体数据的键值确定类型并进行分类处理。
    注意：雷达数据现在通过HTTP接收，不再在这里处理
    """
    classified = classify_data(item, source=DataSource.TCP)
    runtime_data_writer.write(classified.kind, item)

    if classified.kind == DataKind.FLOW:  # 流量数据
        # logger.debug("Traffic flow data")
        add_to_flow_window(item)
        if item.get("jtll_ddbh") in ['1','2','3','4']:
            traffic_count+=1
    elif classified.kind == DataKind.QUEUE:  # 排队数据
        # logger.debug("Queue data")
        add_to_queue_window(item)
    elif classified.kind == DataKind.STAGE: #stage数据
        add_to_stage_window(item)
        # logger.debug("Stage data")
    elif classified.kind == DataKind.HEARTBEAT:  # 心跳包
        logger.debug("Heartbeat data" )
    elif classified.kind == DataKind.ONLINE: # 互联网数据1
        # logger.debug('online data')
        if item['rid'] in Lambdas.online_data_map_lambda:
            add_to_online_window(item)
    elif classified.kind == DataKind.LATEST:
        if item['inter_id'] in Lambdas.latest_data_map_lambda:
            add_to_latest_window(item)
    elif classified.kind == DataKind.EXTEND:  # extend数据
        if item.get("CrossId") in Lambdas.intersection_list:
            add_to_extend_window(item)
    elif classified.kind == DataKind.OVERFLOW_WARNING:
        logger.info("Overflow warning data")
        ddbh= int(item.get("jtll_ddbh"))
        logger.info(f"Overflow warning for ddbh: {ddbh}")
        if ddbh in Lambdas.location_to_intersection_lambda:
            intersection_id,direction=Lambdas.location_to_intersection_lambda[ddbh]
            logger.info(f"Intersection ID: {intersection_id}, Direction: {direction}")
            overflowWarningMap[intersection_id][direction]=item 
    else:  # 其他历史数据
        logger.info("Historical data")

################# 数据流输入结束#############################

        
def start_server():
    nacos_floating_value_sync.start()
    nacos_intersection_result_sync.start()
    nacos_road_state_sync.start()
    nacos_time_schedule_sync.start()
    # 启动HTTP雷达数据接收服务器
    radar_server, radar_thread = start_radar_http_server()
    if radar_server is None:
        logger.error("Failed to start radar HTTP server, exiting...")
        return
    
    # 启动数据处理和广播线程
    threading.Thread(target=periodic_data_processing, daemon=True).start()
    logger.info("Data processing thread started.")
    threading.Thread(target=broadcast_results, daemon=True).start()
    logger.info("Broadcast results thread started.")  

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((HOST, PORT))
        server_socket.listen()
        logger.info(f"Main server started on {HOST}:{PORT}")
        logger.info(f"Radar HTTP server running on {RADAR_HTTP_HOST}:{RADAR_HTTP_PORT}")
        Flow_predict.setup_scheduler(pre_hour, pre_min)
        Queue_predict.setup_scheduler(pre_hour, pre_min)
        logger.info(f'Flow & Queue prediction scheduler set,job will start at {pre_hour}:{pre_min}')
        while True:
            client_socket, address = server_socket.accept()
            logger.info(f"New connection from {address}")
            threading.Thread(target=handle_client, args=(client_socket, address)).start()

# 停止服务器信号处理
def stop_server(signal, frame):
    logger.info("Stopping server...")
    nacos_floating_value_sync.stop()
    nacos_intersection_result_sync.stop()
    nacos_road_state_sync.stop()
    nacos_time_schedule_sync.stop()
    # 停止HTTP服务器
    http_server_shutdown.set()
    
    for exit_flag in exit_flags.values():
        exit_flag.set()
    for thread in client_threads:
        thread.join()
    sys.exit(0)

signal.signal(signal.SIGINT, stop_server)

if __name__ == "__main__":
    start_server()
