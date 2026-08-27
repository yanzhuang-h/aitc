"""AITC 运行应用的装配与生命周期管理。"""

from __future__ import annotations

import copy
import threading
from functools import partial
from typing import Any

import Flow_predict
import Queue_predict
import Lambdas
from lib.Global_intersection_coordinate import coordinate
from phase_check import phase_check

from app.config import RuntimeSettings

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
from infra.data.output_store import FileRuntimeOutputStore

from .decision_pipeline import PeriodicDecisionPipeline
from .http_server import HttpRuntimeServer
from .prediction_scheduler import PredictionScheduler
from .prediction_service import FlowPredictionService, QueuePredictionService
from .result_formatter import format_result
from .tcp_server import TcpRuntimeServer
from agent.qwen_agent import QwenSignalTimingAgent, QwenToolRouterAgent, SymbolicDataAgent
from agent.control_agent import ControlProcessAgent
from agent.harness import AgentHarness
from agent.tools import DataQueryTools
from app.core.control.synergy.green_wave_service import GreenWaveDataService
from app.infrastructure.llm import OpenAICompatibleLLMClient
from app.core.tools import SingleIntersectionSignalTimingTool
from app.core.tools.control_function_tools import ControlFunctionTools
from app.core.tools.legacy_algorithms import DQN_select


class AITCApplication:
    """协调数据服务、决策管线与配置同步的应用生命周期。"""

    def __init__(self, *, config_sync_manager, http_server, tcp_server, decision_pipeline, prediction_scheduler, send_interval, enable_config_sync=True, enable_prediction_scheduler=True, llm_client=None, llm_required=False, logger=None):
        self.config_sync_manager = config_sync_manager
        self.http_server = http_server
        self.tcp_server = tcp_server
        self.decision_pipeline = decision_pipeline
        self.prediction_scheduler = prediction_scheduler
        self.send_interval = send_interval
        self.enable_config_sync = enable_config_sync
        self.enable_prediction_scheduler = enable_prediction_scheduler
        self.llm_client = llm_client
        self.llm_required = llm_required
        self.logger = logger
        self._stop_event = threading.Event()
        self._decision_thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        if self.llm_client is not None:
            self._check_llm_ready()
        if self.enable_config_sync:
            self.config_sync_manager.start()
        self.http_server.start()
        self._decision_thread = threading.Thread(target=self._run_decision_loop, daemon=True)
        self._decision_thread.start()
        self.tcp_server.start_broadcast_thread()
        if self.enable_prediction_scheduler:
            self.prediction_scheduler.start()
        self._info("AITC application started")

    def _check_llm_ready(self) -> None:
        """启动时检查 LLM 服务是否就绪。

        就绪则记录 INFO；不可达时按 llm_required 决定告警降级或直接启动失败。
        """
        try:
            self.llm_client.list_models()
            self._info(
                "LLM 服务已就绪: %s (model=%s)",
                getattr(self.llm_client, "base_url", "?"),
                getattr(self.llm_client, "model", "?"),
            )
        except Exception as error:
            if self.llm_required:
                self._error("LLM 服务不可用且 llm_required=true，应用启动失败: %s", error)
                raise RuntimeError(f"LLM service is required but unavailable: {error}") from error
            self._warning("LLM 服务不可用，Agent 相关功能将降级: %s", error)

    def run(self) -> None:
        self.start()
        self.tcp_server.serve_forever()

    def stop(self) -> None:
        self._stop_event.set()
        if self.enable_config_sync:
            self.config_sync_manager.stop()
        if self.enable_prediction_scheduler:
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

    def _warning(self, message, *args):
        if self.logger is not None:
            self.logger.warning(message, *args)

    def _error(self, message, *args, **kwargs):
        if self.logger is not None:
            self.logger.error(message, *args, **kwargs)


def create_application(logger=None, settings: RuntimeSettings | None = None) -> AITCApplication:
    """按当前兼容配置创建完整运行应用。"""
    settings = (settings or RuntimeSettings.from_environment()).validate()
    cache = ShortTermMemory({
        DataKind.FLOW: 600, DataKind.QUEUE: 240, DataKind.STAGE: 600,
        DataKind.EXTEND: 600, DataKind.ONLINE: 1800, DataKind.LATEST: 1800,
        DataKind.RADAR: 600, DataKind.BOYAN: 600,
    })
    writer = RuntimeDataWriter(FileRuntimeOutputStore(settings.runtime_output_dir))
    repository = LongTermMemory(root=settings.runtime_data_dir)
    overflow_warning_map = copy.deepcopy(Lambdas.map_lambda)
    quality_monitor = DataQualityMonitor()
    radar_event_map = {key: {} for key in Lambdas.radar_event_list}
    receiver = RuntimeDataReceiver(cache=cache, writer=writer, repository=repository, lambdas_module=Lambdas, overflow_warning_map=overflow_warning_map, radar_event_map=radar_event_map, logger=logger, quality_monitor=quality_monitor)
    ingestor = RuntimeDataIngestor(receiver)
    config_service = ConfigService()
    warehouse = ResultWarehouse()
    query_service = MemoryQueryLayer(short_term_memory=cache, result_warehouse=warehouse, config_service=config_service, long_term_memory=repository, quality_monitor=quality_monitor)
    sender = ResultSender(writer=writer, logger=logger)
    prediction_repository = FilePredictionRepository(root=settings.prediction_data_dir)
    flow_predictor = FlowPredictionService(Flow_predict, prediction_repository)
    queue_predictor = QueuePredictionService(Queue_predict, prediction_repository)
    signal_timing_tool = SingleIntersectionSignalTimingTool()
    data_tools = DataQueryTools(query_service, signal_timing_tool=signal_timing_tool)
    control_processor = RuntimeDataProcessor(cache, Lambdas)
    control_tools = ControlFunctionTools(
        data_processor=control_processor,
        overflow_warning_map=overflow_warning_map,
        radar_event_map=radar_event_map,
        flow_duration_seconds=settings.flow_duration_seconds,
    )
    control_tools.merge_into(data_tools.registry)
    qwen_client = OpenAICompatibleLLMClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        default_max_tokens=settings.llm_max_tokens,
        enable_thinking=settings.llm_enable_thinking,
    )
    qwen_agent = QwenSignalTimingAgent(qwen_client, data_tools)
    qwen_tool_router_agent = QwenToolRouterAgent(qwen_client, data_tools)
    symbolic_agent = SymbolicDataAgent(data_tools)
    control_process_agent = ControlProcessAgent(qwen_client, query_service=query_service, logger=logger)
    green_wave_service = GreenWaveDataService(logger=logger)
    agent_harness = AgentHarness(
        signal_timing_tool=signal_timing_tool,
        symbolic_agent=symbolic_agent,
        qwen_agent=qwen_agent,
        control_process_agent=control_process_agent,
        qwen_tool_router_agent=qwen_tool_router_agent,
        green_wave_service=green_wave_service,
        logger=logger,
    )
    http_server = HttpRuntimeServer(host=settings.http_host, port=settings.http_port, ingestor=ingestor, config_service=config_service, query_service=query_service, agent_harness=agent_harness, green_wave_service=green_wave_service, logger=logger)
    tcp_server = TcpRuntimeServer(host=settings.tcp_host, port=settings.tcp_port, buffer_size=settings.tcp_buffer_size, ingestor=ingestor, result_warehouse=warehouse, result_sender=sender, send_interval=settings.result_send_interval_seconds, logger=logger)
    pipeline = PeriodicDecisionPipeline(cache=cache, data_processor=control_processor, lambdas_module=Lambdas, writer=writer, result_warehouse=warehouse, flow_predictor=flow_predictor, queue_predictor=queue_predictor, dqn_select=DQN_select, coordinate=coordinate, phase_check=phase_check, select_data_to_send=partial(format_result, lambdas_module=Lambdas), is_millisecond_timestamp=is_millisecond_timestamp, overflow_warning_map=overflow_warning_map, radar_event_map=radar_event_map, flow_duration_seconds=settings.flow_duration_seconds, logger=logger)
    prediction_scheduler = PredictionScheduler(flow_job=flow_predictor.daily_prediction_job, queue_job=queue_predictor.daily_queue_prediction, hour=settings.prediction_hour, minute=settings.prediction_minute, logger=logger)
    return AITCApplication(config_sync_manager=ConfigSyncManager(), http_server=http_server, tcp_server=tcp_server, decision_pipeline=pipeline, prediction_scheduler=prediction_scheduler, send_interval=settings.decision_interval_seconds, enable_config_sync=settings.enable_config_sync, enable_prediction_scheduler=settings.enable_prediction_scheduler, llm_client=qwen_client, llm_required=settings.llm_required, logger=logger)
