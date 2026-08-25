"""控制函数工具集：把 lib.control_functions 稳定入口注册为 Agent 工具。

依据《路口控制函数化与大模型调用说明.md》：
- ``generate_intersection_plan``：单路口初始方案（DQN 调度）
- ``get_timetable_plan``：异常路径的固定时刻表方案
- ``process_all_intersections``：Internet→mixed→flow 完整处理（推荐全局入口）

提供 ``data_processor`` 时，单路口工具自动从数据底座聚合实时上下文，
Agent 只需传入 ``cross_id``。本模块只调用 lib，不修改 lib 实现。
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Mapping
from typing import Any

import Lambdas
from agent.registry import ToolRegistry
from app.core.models import ToolResponse
from lib.control_functions import (
    IntersectionControlRequest,
    generate_intersection_plan,
    get_timetable_plan,
    process_all_intersections,
)


class ControlFunctionTools:
    """面向 Agent 的路口控制函数工具集。"""

    DEFAULT_FLOW_DURATION_SECONDS = 300

    def __init__(
        self,
        *,
        data_processor: Any | None = None,
        lambdas_module: Any = Lambdas,
        overflow_warning_map: Mapping[str, Any] | None = None,
        radar_event_map: Mapping[str, Any] | None = None,
        flow_duration_seconds: int = DEFAULT_FLOW_DURATION_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.data_processor = data_processor
        self.lambdas = lambdas_module
        self.overflow_warning_map = overflow_warning_map
        self.radar_event_map = radar_event_map
        self.flow_duration_seconds = flow_duration_seconds
        self.clock = clock
        self._registry = ToolRegistry()
        self._register_tools()

    # ------------------------------------------------------------------ 注册

    def _register_tools(self) -> None:
        self._registry.register(
            "generate_intersection_plan",
            "生成单个路口的初始放行控制方案（DQN 调度）。优先提供 cross_id，"
            "工具自动从数据底座取实时上下文；也可显式传入各数据源 map 覆盖。",
            {
                "type": "object",
                "properties": {
                    "cross_id": {"type": "string", "description": "路口编号。"},
                    "current_time": {"type": "number", "description": "可选 Unix 秒时间戳，默认当前时间。"},
                    "flow_map": {"type": "object", "description": "可选，路口流量时序数据，显式传入时覆盖自动上下文。"},
                    "queue_map": {"type": "object"},
                    "stage_map": {"type": "object"},
                    "extend_map": {"type": "object"},
                    "overflow_map": {"type": "object"},
                    "radar_map": {"type": "object"},
                    "boyan_map": {"type": "object"},
                },
                "required": ["cross_id"],
            },
            self._handle_generate_intersection_plan,
            action="control.plan.single",
        )
        self._registry.register(
            "get_timetable_plan",
            "读取指定路口工作日/周末当前小时的固定时刻表方案（异常路径）。",
            {
                "type": "object",
                "properties": {
                    "cross_id": {"type": "string", "description": "路口编号。"},
                    "target_time": {"description": "可选目标时间（ISO 字符串或 Unix 秒），默认当前时间。"},
                },
                "required": ["cross_id"],
            },
            self._handle_get_timetable_plan,
            action="control.timetable",
        )
        self._registry.register(
            "process_all_intersections",
            "按 Internet→mixed→flow 顺序处理完整路口快照，返回最终非绿波全局控制方案（推荐入口）。",
            {
                "type": "object",
                "properties": {
                    "plans": {"type": "object", "description": "路口编号到十元素方案的映射，必填。"},
                    "coordinate_data": {"type": "object", "description": "路口相位起点信息。"},
                    "online_data": {"type": "object", "description": "互联网在线观测。"},
                    "overflow_data": {"type": "object", "description": "溢出预警数据。"},
                    "extend_data": {"type": "object", "description": "路口扩展数据。"},
                },
                "required": ["plans"],
            },
            self._handle_process_all_intersections,
            action="control.process_all",
        )

    # ------------------------------------------------------------------ handler

    def _handle_generate_intersection_plan(self, **kwargs: Any) -> dict[str, Any]:
        cross_id = str(kwargs.get("cross_id") or "").strip()
        if not cross_id:
            return ToolResponse.error("cross_id 不能为空").to_dict()
        current_time = float(kwargs.get("current_time") or self.clock())
        try:
            request = self._build_intersection_request(cross_id, current_time, kwargs)
            result = generate_intersection_plan(request)
        except Exception as exc:
            return ToolResponse.error(
                f"生成路口方案失败: {type(exc).__name__}: {exc}"
            ).to_dict()
        if not result.success:
            return ToolResponse.error(
                result.error or "方案生成失败", meta={"cross_id": cross_id}
            ).to_dict()
        return ToolResponse.ok(
            summary=f"路口 {cross_id} 初始方案已生成（来源 {result.source}）",
            data=result.to_dict(),
            meta={"cross_id": cross_id, "source": result.source},
        ).to_dict()

    def _handle_get_timetable_plan(self, **kwargs: Any) -> dict[str, Any]:
        cross_id = str(kwargs.get("cross_id") or "").strip()
        if not cross_id:
            return ToolResponse.error("cross_id 不能为空").to_dict()
        try:
            result = get_timetable_plan(cross_id, kwargs.get("target_time"))
        except Exception as exc:
            return ToolResponse.error(
                f"读取时刻表方案失败: {type(exc).__name__}: {exc}"
            ).to_dict()
        if not result.success:
            return ToolResponse.error(
                result.error or "时刻表方案不可用", meta={"cross_id": cross_id}
            ).to_dict()
        return ToolResponse.ok(
            summary=f"路口 {cross_id} 时刻表方案已读取（来源 {result.source}）",
            data=result.to_dict(),
            meta={"cross_id": cross_id, "source": result.source},
        ).to_dict()

    def _handle_process_all_intersections(self, **kwargs: Any) -> dict[str, Any]:
        plans = kwargs.get("plans")
        if not isinstance(plans, dict) or not plans:
            return ToolResponse.error("plans 必须是非空的路口方案映射").to_dict()
        try:
            result = process_all_intersections(
                plans,
                kwargs.get("coordinate_data") or {},
                kwargs.get("online_data") or {},
                kwargs.get("overflow_data") or {},
                kwargs.get("extend_data"),
            )
        except Exception as exc:
            return ToolResponse.error(
                f"全局处理失败: {type(exc).__name__}: {exc}"
            ).to_dict()
        return ToolResponse.ok(
            summary="全局路口方案已处理完成",
            data=result,
            meta={"intersection_count": len(result)},
        ).to_dict()

    # ------------------------------------------------------------ 上下文构造

    def _build_intersection_request(
        self,
        cross_id: str,
        current_time: float,
        kwargs: Mapping[str, Any],
    ) -> IntersectionControlRequest:
        if self.data_processor is None:
            # 无数据底座时，使用 lambdas 默认值填充（对齐既有单路口工具），
            # 避免 DQN 在空向量上出现下标越界；显式传入的 map 优先。
            lambdas = self.lambdas
            return IntersectionControlRequest(
                cross_id=cross_id,
                current_time=current_time,
                traffic_vector=list(
                    kwargs.get("traffic_vector")
                    or copy.deepcopy(
                        lambdas.intersection_flow_lambda.get(cross_id, [0, 0, 0, 0])
                    )
                ),
                queue_vector=dict(
                    kwargs.get("queue_vector")
                    or copy.deepcopy(lambdas.max_lengths_lambda.get(cross_id, {}))
                ),
                flow_map=dict(
                    kwargs.get("flow_map")
                    or copy.deepcopy(lambdas.map_lambda.get(cross_id, {}))
                ),
                queue_map=dict(kwargs.get("queue_map") or {}),
                stage_map=dict(kwargs.get("stage_map") or {}),
                extend_map=dict(kwargs.get("extend_map") or {}),
                overflow_map=dict(kwargs.get("overflow_map") or {}),
                radar_map=dict(kwargs.get("radar_map") or {}),
                boyan_map=dict(kwargs.get("boyan_map") or {}),
            )
        processor = self.data_processor
        flow = processor.flow()
        flow_duration2 = processor.flow_duration(self.flow_duration_seconds)
        queue = processor.queue()
        overflow = processor.radar_event(
            self.radar_event_map or {},
            self.overflow_warning_map or {},
        )
        return IntersectionControlRequest(
            cross_id=cross_id,
            current_time=current_time,
            traffic_vector=flow[0].get(cross_id, []),
            queue_vector=queue[0].get(cross_id, {}),
            traffic_vector_duration2=flow_duration2[0].get(cross_id, []),
            flow_map=dict(flow[1].get(cross_id, {})),
            queue_map=dict(queue[1].get(cross_id, {})),
            stage_map=dict(processor.stage().get(cross_id, {})),
            extend_map=dict(processor.extend().get(cross_id, {})),
            overflow_map=dict(overflow.get(cross_id, {})),
            radar_map=dict(processor.radar().get(cross_id, {})),
            boyan_map=dict(processor.boyan().get(cross_id, {})),
        )

    # ------------------------------------------------------ 注册表访问（对齐既有工具集）

    def tool_schemas(self) -> list[dict[str, Any]]:
        return self._registry.tool_schemas()

    def actions(self) -> dict[str, str]:
        return self._registry.actions()

    def invoke(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._registry.invoke(name, arguments)

    def merge_into(self, target: ToolRegistry) -> None:
        """把本工具集注册的工具合并进目标注册中心（供统一工具集使用）。"""
        for spec in self._registry.all_specs():
            target.register(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
                handler=spec.handler,
                action=spec.action,
            )

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def __len__(self) -> int:
        return len(self._registry)
