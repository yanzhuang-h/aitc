import copy
import threading
import time
import json
import socket
import Flow_predict
import Queue_predict
# import torch
from datetime import datetime
from Select_data_to_send import select_data_to_send
import sys
import signal
import Write_to_file
import Lambdas
import logging  # 添加日志模块
import logging.handlers  # 添加日志处理器
from phase_check import phase_check
from lib.DQN_Select import DQN_select
from lib.Global_intersection_coordinate import coordinate
from runtime import PeriodicDecisionPipeline
from infra.data import (
    ConfigService,
    DataRepository,
    ConfigSyncManager,
    DataKind,
    LegacyCacheProcessor,
    RuntimeDataCache,
    RuntimeDataIngestor,
    RuntimeDataQueryService,
    RuntimeDataReceiver,
    RuntimeDataWriter,
    ResultSender,
    ResultWarehouse,
    is_millisecond_timestamp,
)

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
config_sync_manager = ConfigSyncManager()
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
legacy_cache_processor = LegacyCacheProcessor(runtime_data_cache)

# 雷达事件map
radar_event_map = {key:{}for key in Lambdas.radar_event_list}

# 服务器配置

#HOST = '172.17.0.11'
# HOST = '11.82.117.80'
HOST = '127.0.0.1'

PORT = 65432
BUFFER_SIZE = 1024 * 1024

# HTTP雷达服务器配置

# RADAR_HTTP_HOST = '172.17.0.11'
# RADAR_HTTP_HOST ='11.82.117.80'
RADAR_HTTP_HOST ='127.0.0.1'


RADAR_HTTP_PORT = 8088

# 文件写入锁
file_lock = threading.Lock()
import_lock = threading.Lock()
# 用于存储所有活动线程和退出标志
client_threads = []
exit_flags = {}

# 定义流量预测任务开始时间
pre_hour=3
pre_min=0

#定义用于测试的数据结构
traffic_count=0
LXD_stage_count=0

clients = []              # 存储所有活跃客户端套接字
clients_lock = threading.Lock()  # 客户端列表的线程锁
result_lock = threading.Lock()   # 计算结果的线程锁

# HTTP服务器关闭标志
http_server_shutdown = threading.Event()

runtime_data_writer = RuntimeDataWriter(Write_to_file)
runtime_data_writer.start_filename_updater()
data_repository = DataRepository()
runtime_data_receiver = RuntimeDataReceiver(
    cache=runtime_data_cache,
    writer=runtime_data_writer,
    repository=data_repository,
    lambdas_module=Lambdas,
    overflow_warning_map=overflowWarningMap,
    radar_event_map=radar_event_map,
    logger=logger,
)
runtime_data_ingestor = RuntimeDataIngestor(runtime_data_receiver)
config_service = ConfigService()
result_warehouse = ResultWarehouse()
runtime_query_service = RuntimeDataQueryService(
    cache=runtime_data_cache,
    result_warehouse=result_warehouse,
    config_service=config_service,
    repository=data_repository,
)
result_sender = ResultSender(writer=runtime_data_writer, logger=logger)
decision_pipeline = PeriodicDecisionPipeline(
    cache=runtime_data_cache,
    legacy_processor=legacy_cache_processor,
    lambdas_module=Lambdas,
    writer=runtime_data_writer,
    result_warehouse=result_warehouse,
    flow_predictor=Flow_predict,
    queue_predictor=Queue_predict,
    dqn_select=DQN_select,
    coordinate=coordinate,
    phase_check=phase_check,
    select_data_to_send=select_data_to_send,
    is_millisecond_timestamp=is_millisecond_timestamp,
    overflow_warning_map=overflowWarningMap,
    radar_event_map=radar_event_map,
    flow_duration_seconds=FLOW_WINDOW_DURATION2,
    logger=logger,
)

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
            outcome = config_service.handle_request(method, urlparse(self.path).path, body)
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
            "radar_cache_size": runtime_query_service.get_runtime_size(DataKind.RADAR)
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
            runtime_data_ingestor.ingest_http_item(item)
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

def periodic_decision_processing():
    """周期触发决策编排，服务端不再直接组织算法调用。"""
    global processing_flag
    while True:
        start_time = time.time()
        while processing_flag:
            time.sleep(0.1)

        processing_flag = True
        try:
            decision_pipeline.run_once()
        except Exception as e:
            logger.error(f"数据处理失败: {e}", exc_info=True)
        finally:
            processing_flag = False
            logger.info("最新结果已更新。。。。")

        elapsed = time.time() - start_time
        time.sleep(max(0, SEND_INTERVAL - elapsed))


def broadcast_results():
    """独立线程：将最新结果广播给所有客户端"""
    while True:
        # 获取当前结果和客户端列表
        with clients_lock:
            current_clients = clients.copy()
        cur_send_set = result_warehouse.snapshot()
        if cur_send_set==[]:
            time.sleep(1)
            continue

        # 向所有客户端发送数据
        disconnected_clients = result_sender.send_batch(current_clients, cur_send_set)
        for client_socket in disconnected_clients:
            with clients_lock:
                if client_socket in clients:
                    clients.remove(client_socket)
            client_socket.close()
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
    classified = runtime_data_ingestor.ingest_tcp_item(item)

    if classified.kind == DataKind.FLOW:  # 流量数据
        if item.get("jtll_ddbh") in ['1','2','3','4']:
            traffic_count+=1

################# 数据流输入结束#############################

        
def start_server():
    config_sync_manager.start()
    # 启动HTTP雷达数据接收服务器
    radar_server, radar_thread = start_radar_http_server()
    if radar_server is None:
        logger.error("Failed to start radar HTTP server, exiting...")
        return
    
    # 启动数据处理和广播线程
    threading.Thread(target=periodic_decision_processing, daemon=True).start()
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
    config_sync_manager.stop()
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
