"""AITC 运行应用的装配与生命周期管理。"""

from __future__ import annotations

import copy
import threading
from functools import partial
from typing import Any

import Flow_predict
import Queue_predict
import Lambdas
from lib.DQN_Select import DQN_select
from lib.Global_intersection_coordinate import coordinate
from phase_check import phase_check

from infra.data import (
    ConfigService,
    ConfigSyncManager,
    DataKind,
    LongTermMemory,
    DataQualityMonitor,
    FilePredictionRepository,
    RuntimeDataProcessor,
    ResultSender,
    ResultWarehouse,
    ShortTermMemory,
    RuntimeDataIngestor,
    MemoryQueryLayer,
    RuntimeDataReceiver,
    RuntimeDataWriter,
    is_millisecond_timestamp,
)

from .decision_pipeline import PeriodicDecisionPipeline
from .http_server import HttpRuntimeServer
from .prediction_scheduler import PredictionScheduler
from .prediction_service import FlowPredictionService, QueuePredictionService
from .result_formatter import format_result
from .tcp_server import TcpRuntimeServer


class AITCApplication:
    """协调数据服务、决策管线与配置同步的应用生命周期。"""

    def __init__(self, *, config_sync_manager, http_server, tcp_server, decision_pipeline, prediction_scheduler, send_interval, logger=None):
        self.config_sync_manager = config_sync_manager
        self.http_server = http_server
        self.tcp_server = tcp_server
        self.decision_pipeline = decision_pipeline
        self.prediction_scheduler = prediction_scheduler
        self.send_interval = send_interval
        self.logger = logger
        self._stop_event = threading.Event()
        self._decision_thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self.config_sync_manager.start()
        self.http_server.start()
        self._decision_thread = threading.Thread(target=self._run_decision_loop, daemon=True)
        self._decision_thread.start()
        self.tcp_server.start_broadcast_thread()
        self.prediction_scheduler.start()
        self._info("AITC application started")

    def run(self) -> None:
        self.start()
        self.tcp_server.serve_forever()

    def stop(self) -> None:
        self._stop_event.set()
        self.config_sync_manager.stop()
        self.prediction_scheduler.stop()
        self.http_server.stop()
        self.tcp_server.stop()
        if self._decision_thread is not None:
            self._decision_thread.join(timeout=self.send_interval + 1)
        self._info("AITC application stopped")

    def _run_decision_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.decision_pipeline.run_once()
            except Exception:
                self._error("数据处理失败", exc_info=True)
            self._stop_event.wait(self.send_interval)

    def _info(self, message, *args):
        if self.logger is not None:
            self.logger.info(message, *args)

    def _error(self, message, *args, **kwargs):
        if self.logger is not None:
            self.logger.error(message, *args, **kwargs)


def create_application(logger=None) -> AITCApplication:
    """按当前兼容配置创建完整运行应用。"""
    cache = ShortTermMemory({
        DataKind.FLOW: 600, DataKind.QUEUE: 240, DataKind.STAGE: 600,
        DataKind.EXTEND: 600, DataKind.ONLINE: 1800, DataKind.LATEST: 1800,
        DataKind.RADAR: 600, DataKind.BOYAN: 600,
    })
    writer = RuntimeDataWriter()
    repository = LongTermMemory()
    overflow_warning_map = copy.deepcopy(Lambdas.map_lambda)
    quality_monitor = DataQualityMonitor()
    radar_event_map = {key: {} for key in Lambdas.radar_event_list}
    receiver = RuntimeDataReceiver(cache=cache, writer=writer, repository=repository, lambdas_module=Lambdas, overflow_warning_map=overflow_warning_map, radar_event_map=radar_event_map, logger=logger, quality_monitor=quality_monitor)
    ingestor = RuntimeDataIngestor(receiver)
    config_service = ConfigService()
    warehouse = ResultWarehouse()
    query_service = MemoryQueryLayer(short_term_memory=cache, result_warehouse=warehouse, config_service=config_service, long_term_memory=repository, quality_monitor=quality_monitor)
    sender = ResultSender(writer=writer, logger=logger)
    prediction_repository = FilePredictionRepository()
    flow_predictor = FlowPredictionService(Flow_predict, prediction_repository)
    queue_predictor = QueuePredictionService(Queue_predict, prediction_repository)
    http_server = HttpRuntimeServer(host="127.0.0.1", port=8088, ingestor=ingestor, config_service=config_service, query_service=query_service, logger=logger)
    tcp_server = TcpRuntimeServer(host="127.0.0.1", port=65432, buffer_size=1024 * 1024, ingestor=ingestor, result_warehouse=warehouse, result_sender=sender, send_interval=50, logger=logger)
    pipeline = PeriodicDecisionPipeline(cache=cache, data_processor=RuntimeDataProcessor(cache, Lambdas), lambdas_module=Lambdas, writer=writer, result_warehouse=warehouse, flow_predictor=flow_predictor, queue_predictor=queue_predictor, dqn_select=DQN_select, coordinate=coordinate, phase_check=phase_check, select_data_to_send=partial(format_result, lambdas_module=Lambdas), is_millisecond_timestamp=is_millisecond_timestamp, overflow_warning_map=overflow_warning_map, radar_event_map=radar_event_map, flow_duration_seconds=150, logger=logger)
    prediction_scheduler = PredictionScheduler(flow_job=flow_predictor.daily_prediction_job, queue_job=queue_predictor.daily_queue_prediction, hour=3, minute=0, logger=logger)
    return AITCApplication(config_sync_manager=ConfigSyncManager(), http_server=http_server, tcp_server=tcp_server, decision_pipeline=pipeline, prediction_scheduler=prediction_scheduler, send_interval=50, logger=logger)
