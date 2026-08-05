import copy
import threading
import time
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
from runtime import HttpRuntimeServer, PeriodicDecisionPipeline, TcpRuntimeServer
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

# 定义流量预测任务开始时间
pre_hour=3
pre_min=0


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
http_runtime_server = HttpRuntimeServer(
    host=RADAR_HTTP_HOST,
    port=RADAR_HTTP_PORT,
    ingestor=runtime_data_ingestor,
    config_service=config_service,
    query_service=runtime_query_service,
    logger=logger,
)
tcp_runtime_server = TcpRuntimeServer(
    host=HOST,
    port=PORT,
    buffer_size=BUFFER_SIZE,
    ingestor=runtime_data_ingestor,
    result_warehouse=result_warehouse,
    result_sender=result_sender,
    send_interval=SEND_INTERVAL,
    logger=logger,
)
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


def start_server():
    config_sync_manager.start()
    http_runtime_server.start()
    
    # 启动数据处理和结果广播线程
    threading.Thread(target=periodic_decision_processing, daemon=True).start()
    logger.info("Data processing thread started.")
    tcp_runtime_server.start_broadcast_thread()
    logger.info("Broadcast results thread started.")  
    logger.info("Radar HTTP server running on %s:%s", *http_runtime_server.address)
    Flow_predict.setup_scheduler(pre_hour, pre_min)
    Queue_predict.setup_scheduler(pre_hour, pre_min)
    logger.info(f'Flow & Queue prediction scheduler set,job will start at {pre_hour}:{pre_min}')
    tcp_runtime_server.serve_forever()

# 停止服务器信号处理
def stop_server(signal, frame):
    logger.info("Stopping server...")
    config_sync_manager.stop()
    http_runtime_server.stop()
    tcp_runtime_server.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, stop_server)

if __name__ == "__main__":
    start_server()
