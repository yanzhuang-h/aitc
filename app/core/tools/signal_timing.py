"""单路口放行时间工具适配器。

本模块只做参数整理和结果规范化，具体算法仍调用 ``lib.DQN_Select.DQN_select``；
参数经统一的 ``IntersectionControlRequest`` 传递。
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Mapping
from typing import Any

import Lambdas
from lib.control_functions.dqn_control import call_dqn_select
from lib.control_functions.types import IntersectionControlRequest


class SingleIntersectionSignalTimingTool:
    """面向 Agent 的单路口放行时间生成工具。"""

    def __init__(
        self,
        *,
        lambdas_module: Any = Lambdas,
        dqn_select: Callable[..., tuple[Any, Any, Any, Any]] = call_dqn_select,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.lambdas = lambdas_module
        self.dqn_select = dqn_select
        self.clock = clock

    def generate(
        self,
        cross_id: str,
        *,
        request_text: str | None = None,
        traffic_vector: list[Any] | None = None,
        queue_vector: Mapping[str, Any] | None = None,
        traffic_vector_duration2: list[Any] | None = None,
        flow_map: Mapping[str, Any] | None = None,
        queue_map: Mapping[str, Any] | None = None,
        stage_map: Mapping[str, Any] | None = None,
        extend_map: Mapping[str, Any] | None = None,
        overflow_map: Mapping[str, Any] | None = None,
        radar_map: Mapping[str, Any] | None = None,
        boyan_map: Mapping[str, Any] | None = None,
        flow_prediction: Mapping[str, Any] | None = None,
        queue_prediction: Mapping[str, Any] | None = None,
        last_coordinate_set: Mapping[str, Any] | None = None,
        current_time: float | None = None,
    ) -> dict[str, Any]:
        """生成单个路口的放行时间。

        调用方可以只传 `cross_id` 做冒烟验证；生产链路应传入数据仓库聚合后的路口上下文。
        """
        if not cross_id:
            raise ValueError("cross_id must not be empty")

        request = IntersectionControlRequest(
            cross_id=cross_id,
            current_time=current_time if current_time is not None else self.clock(),
            traffic_vector=list(traffic_vector) if traffic_vector is not None else self._default_traffic_vector(cross_id),
            queue_vector=self._mapping_or_default(queue_vector, "max_lengths_lambda", cross_id),
            traffic_vector_duration2=list(traffic_vector_duration2) if traffic_vector_duration2 is not None else self._default_traffic_vector(cross_id),
            flow_map=dict(flow_map or {}),
            queue_map=dict(queue_map or {}),
            stage_map=dict(stage_map or {}),
            previous_coordinate=copy.deepcopy(last_coordinate_set) if last_coordinate_set is not None else copy.deepcopy(self.lambdas.map_lambda),
            predicted_flow=dict(flow_prediction or {}),
            predicted_queue=dict(queue_prediction or {}),
            extend_map=dict(extend_map or {}),
            overflow_map=dict(overflow_map or {}),
            radar_map=dict(radar_map or {}),
            boyan_map=dict(boyan_map or {}),
        )
        action, coordinate_set, model_info, experience = self.dqn_select(request)
        return {
            "cross_id": cross_id,
            "signal_timing": action,
            "coordinate_set": coordinate_set,
            "model_info": model_info,
            "experience": experience,
        }

    def _default_traffic_vector(self, cross_id: str) -> list[Any]:
        source = getattr(self.lambdas, "intersection_flow_lambda", {})
        return list(copy.deepcopy(source.get(cross_id, [0, 0, 0, 0])))

    def _mapping_or_default(
        self,
        value: Mapping[str, Any] | None,
        default_name: str,
        cross_id: str,
    ) -> dict[str, Any]:
        if value is not None:
            return dict(value)
        source = getattr(self.lambdas, default_name, {})
        return dict(copy.deepcopy(source.get(cross_id, {})))
