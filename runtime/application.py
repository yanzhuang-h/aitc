"""AITC 运行应用的装配与生命周期管理。"""

from __future__ import annotations

import copy
import threading
import time
from functools import partial
from typing import Any

import Flow_predict
import Queue_predict
import Lambdas
from lib.Global_intersection_coordinate import coordinate
from phase_check import phase_check

from app.config import RuntimeSettings
from app.core.control.policies import BaselineController

from infra.data import (
    ConfigService,
    ConfigSyncManager,
    LongTermMemory,
    DataQualityMonitor,
    FilePredictionRepository,
    RuntimeDataProcessor,
    ResultSender,
    ResultWarehouse,
    ShortTermMemory,
    TrafficDataHub,
    RuntimeDataIngestor,
    MemoryQueryLayer,
    RuntimeDataReceiver,
    RuntimeDataWriter,
    is_millisecond_timestamp,
)
from infra.data.output_store import FileRuntimeOutputStore
from infra.logging import LoggingMixin

from .decision_pipeline import PeriodicDecisionPipeline
from .http_server import HttpRuntimeServer
from .prediction_scheduler import PredictionScheduler
from .prediction_service import FlowPredictionService, QueuePredictionService
from .result_formatter import format_result
from .tcp_server import TcpRuntimeServer
from agent.qwen_agent import QwenSignalTimingAgent, QwenToolRouterAgent, SymbolicDataAgent
from agent.control_agent import ControlProcessAgent
from agent.harness import AgentHarness
from agent.experts import EVExpert, InternetExpert, RadarExpert, VideoExpert
from agent.graph import ControlGraph
from agent.tools import DataQueryTools
from app.core.control.synergy.green_wave_service import GreenWaveDataService
from app.infrastructure.llm import (
    DisabledProvider, MockProvider, ModelGateway, OpenAICompatibleLLMClient, QwenProvider,
    as_model_gateway,
)
from app.core.tools import SingleIntersectionSignalTimingTool
from app.core.tools.control_function_tools import ControlFunctionTools
from lib.control_functions.dqn_control import call_dqn_select
from lib.data_ANS.experience_runtime import ExperiencePoolScheduler


class AITCApplication(LoggingMixin):
    """协调数据服务、决策管线与配置同步的应用生命周期。"""

    def __init__(
        self,
        *,
        config_sync_manager,
        http_server,
        tcp_server,
        decision_pipeline,
        prediction_scheduler,
        decision_interval,
        enable_config_sync=False,
        enable_prediction_scheduler=True,
        experience_pool_scheduler=None,
        llm_client=None,
        llm_required=False,
        logger=None,
        datahub=None,
        experts=None,
        decision_graph=None,
        model_gateway=None,
    ):
        self.datahub = datahub
        self.experts = experts if experts is not None else {}
        self.decision_graph = decision_graph
        self.model_gateway = (
            model_gateway if model_gateway is not None
            else as_model_gateway(llm_client) if llm_client is not None else None
        )
        self.config_sync_manager = config_sync_manager
        self.http_server = http_server
        self.tcp_server = tcp_server
        self.decision_pipeline = decision_pipeline
        self.prediction_scheduler = prediction_scheduler
        self.experience_pool_scheduler = experience_pool_scheduler
        self.decision_interval = decision_interval
        self.enable_config_sync = enable_config_sync
        self.enable_prediction_scheduler = enable_prediction_scheduler
        self.llm_client = llm_client
        self.llm_required = llm_required
        self.logger = logger
        self._stop_event = threading.Event()
        self._decision_thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        if self.model_gateway is not None and self.model_gateway.enabled:
            self._check_llm_ready()
        if self.enable_config_sync:
            self.config_sync_manager.start()
        self.http_server.start()
        self._decision_thread = threading.Thread(target=self._run_decision_loop, daemon=True)
        self._decision_thread.start()
        self.tcp_server.start_broadcast_thread()
        if self.enable_prediction_scheduler:
            self.prediction_scheduler.start()
        if self.experience_pool_scheduler is not None:
            self.experience_pool_scheduler.start()
        self._info("AITC application started")

    def _check_llm_ready(self) -> None:
        """启动时检查 LLM 服务是否就绪。

        就绪则记录 INFO；不可达时按 llm_required 决定告警降级或直接启动失败。
        """
        try:
            self.model_gateway.check_ready()
            self._info(
                "LLM 服务已就绪: %s (model=%s)",
                self.model_gateway.base_url,
                self.model_gateway.model,
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
        if self.experience_pool_scheduler is not None:
            self.experience_pool_scheduler.stop()
        self.http_server.stop()
        self.tcp_server.stop()
        if self._decision_thread is not None:
            self._decision_thread.join(timeout=self.decision_interval + 1)
        self._info("AITC application stopped")

    def _run_decision_loop(self) -> None:
        while not self._stop_event.is_set():
            started_at = time.monotonic()
            try:
                self.decision_pipeline.run_once()
            except Exception:
                self._error("数据处理失败", exc_info=True)
            self._stop_event.wait(max(0.0, self.decision_interval - (time.monotonic() - started_at)))


def create_application(logger=None, settings: RuntimeSettings | None = None) -> AITCApplication:
    """装配完整运行应用：数据底座 → 决策管线 → Agent → 协议服务与调度。"""
    settings = (settings or RuntimeSettings.from_environment()).validate()

    # ── ① 数据底座：接收、缓存、长期仓库、聚合、查询、配置与结果收发 ──
    # 窗口缓存：各类型窗口时长使用 ShortTermMemory 的默认表（flow 600s / queue 240s / online·latest 1800s …）
    cache = ShortTermMemory()
    # 兼容日志输出（logs_data/<类别>/<日期>_<类别>.txt，保留旧系统格式）
    writer = RuntimeDataWriter(
        FileRuntimeOutputStore(settings.runtime_output_dir),
        experience_manifest_path=settings.experience_release.active_manifest_path,
    )
    # 长期仓库（infra/data/runtime/runtime/*.jsonl，供历史查询）
    repository = LongTermMemory(root=settings.runtime_data_dir)
    # 溢出告警表：初始结构与 map_lambda 一致，按「路口×方向」记录最新告警
    overflow_warning_map = copy.deepcopy(Lambdas.map_lambda)
    quality_monitor = DataQualityMonitor()
    # 雷达事件表：eventType → deviceNo → 最新事件
    radar_event_map = {key: {} for key in Lambdas.radar_event_list}
    datahub = TrafficDataHub(
        cache=cache, lambdas_module=Lambdas,
        overflow_warning_map=overflow_warning_map, radar_event_map=radar_event_map,
        memory_window=settings.traffic_memory.memory_window,
        event_limit=settings.traffic_memory.datahub_event_limit, logger=logger,
    )
    experts = {
        "video": VideoExpert(datahub, flow_duration_seconds=settings.flow_duration_seconds),
        "radar": RadarExpert(datahub),
        "internet": InternetExpert(datahub),
        "ev": EVExpert(datahub),
    }
    receiver = RuntimeDataReceiver(cache=cache, writer=writer, repository=repository, lambdas_module=Lambdas, overflow_warning_map=overflow_warning_map, radar_event_map=radar_event_map, logger=logger, quality_monitor=quality_monitor, datahub=datahub)
    ingestor = RuntimeDataIngestor(receiver)
    config_service = ConfigService()
    warehouse = ResultWarehouse()
    query_service = MemoryQueryLayer(short_term_memory=cache, result_warehouse=warehouse, config_service=config_service, long_term_memory=repository, quality_monitor=quality_monitor, datahub=datahub)
    sender = ResultSender(writer=writer, logger=logger)
    prediction_repository = FilePredictionRepository(root=settings.prediction_data_dir)
    flow_predictor = FlowPredictionService(Flow_predict, prediction_repository)
    queue_predictor = QueuePredictionService(Queue_predict, prediction_repository)
    # ── ② Agent 层：查询/控制工具、Qwen 客户端与 Harness ──
    signal_timing_tool = SingleIntersectionSignalTimingTool()
    data_tools = DataQueryTools(query_service, signal_timing_tool=signal_timing_tool)
    control_processor = RuntimeDataProcessor(cache, Lambdas, datahub=datahub)
    control_tools = ControlFunctionTools(
        data_processor=control_processor,
        overflow_warning_map=overflow_warning_map,
        radar_event_map=radar_event_map,
        flow_duration_seconds=settings.flow_duration_seconds,
    )
    # 控制工具并入统一注册中心：Agent 与 MCP 共用同一份工具表
    control_tools.merge_into(data_tools.registry)
    model_settings = settings.model_settings
    if model_settings.effective_provider == "disabled":
        model_gateway = ModelGateway(DisabledProvider())
    elif model_settings.effective_provider == "mock":
        model_gateway = ModelGateway(MockProvider())
    else:
        model_gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(
            base_url=model_settings.base_url,
            model=model_settings.name,
            api_key=model_settings.api_key,
            timeout_seconds=model_settings.timeout_seconds,
            default_max_tokens=model_settings.max_tokens,
            enable_thinking=model_settings.enable_thinking,
        )))
    # llm_client 是旧装配属性；生产代理与启动检查均使用同一个 gateway。
    qwen_client = model_gateway if model_gateway.enabled else None
    qwen_agent = None
    qwen_tool_router_agent = None
    control_process_agent = None
    if model_gateway.enabled:
        qwen_agent = QwenSignalTimingAgent(qwen_client, data_tools)
        qwen_tool_router_agent = QwenToolRouterAgent(qwen_client, data_tools)
        control_process_agent = ControlProcessAgent(qwen_client, query_service=query_service, logger=logger)
    symbolic_agent = SymbolicDataAgent(data_tools)
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
    # ── ③ 服务与调度：HTTP / TCP 服务、周期决策管线、预测与经验池调度 ──
    http_server = HttpRuntimeServer(host=settings.http_host, port=settings.http_port, ingestor=ingestor, config_service=config_service, query_service=query_service, agent_harness=agent_harness, green_wave_service=green_wave_service, logger=logger)
    tcp_server = TcpRuntimeServer(host=settings.tcp_host, port=settings.tcp_port, buffer_size=settings.tcp_buffer_size, ingestor=ingestor, result_warehouse=warehouse, result_sender=sender, send_interval=settings.result_send_interval_seconds, logger=logger)
    control_policy = BaselineController(selector=call_dqn_select, coordinator=coordinate)
    decision_graph = ControlGraph(
        datahub, primary_expert=experts["video"], fallback_expert=experts["radar"],
        control_policy=control_policy, logger=logger,
    )
    pipeline = PeriodicDecisionPipeline(cache=cache, data_processor=control_processor, lambdas_module=Lambdas, writer=writer, result_warehouse=warehouse, flow_predictor=flow_predictor, queue_predictor=queue_predictor, control_policy=control_policy, phase_check=phase_check, select_data_to_send=partial(format_result, lambdas_module=Lambdas), is_millisecond_timestamp=is_millisecond_timestamp, overflow_warning_map=overflow_warning_map, radar_event_map=radar_event_map, flow_duration_seconds=settings.flow_duration_seconds, logger=logger, control_snapshot_enabled=settings.control_snapshot_enabled, control_snapshot_dir=settings.control_snapshot_dir, datahub=datahub, decision_graph=decision_graph)
    prediction_scheduler = PredictionScheduler(flow_job=flow_predictor.daily_prediction_job, queue_job=queue_predictor.daily_queue_prediction, hour=settings.prediction_hour, minute=settings.prediction_minute, logger=logger)
    experience_pool_scheduler = (
        ExperiencePoolScheduler(logger=logger, release_settings=settings.experience_release)
        if settings.enable_experience_pool_scheduler
        else None
    )
    return AITCApplication(config_sync_manager=ConfigSyncManager(), http_server=http_server, tcp_server=tcp_server, decision_pipeline=pipeline, prediction_scheduler=prediction_scheduler, experience_pool_scheduler=experience_pool_scheduler, decision_interval=settings.decision_interval_seconds, enable_config_sync=settings.enable_config_sync, enable_prediction_scheduler=settings.enable_prediction_scheduler, llm_client=qwen_client, llm_required=settings.llm_required and model_gateway.enabled, logger=logger, datahub=datahub, experts=experts, decision_graph=decision_graph, model_gateway=model_gateway)
