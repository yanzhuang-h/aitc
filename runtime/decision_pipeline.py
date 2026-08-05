"""周期决策编排。

本模块负责连接数据底座、遗留聚合适配层和既有算法，不修改任何算法实现。
"""

from __future__ import annotations

import copy
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from infra.data.classifier import DataKind


class PeriodicDecisionPipeline:
    """执行一次从实时窗口到下发结果仓库的完整决策流程。"""

    def __init__(
        self,
        *,
        cache: Any,
        data_processor: Any,
        lambdas_module: Any,
        writer: Any,
        result_warehouse: Any,
        flow_predictor: Any,
        queue_predictor: Any,
        dqn_select: Callable[..., tuple[Any, Any, Any, Any]],
        coordinate: Callable[..., dict[str, Any]],
        phase_check: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]],
        select_data_to_send: Callable[..., dict[str, Any]],
        is_millisecond_timestamp: Callable[[Any], bool],
        overflow_warning_map: dict[str, Any],
        radar_event_map: dict[str, Any],
        flow_duration_seconds: int,
        worker_count: int = 30,
        logger: Any | None = None,
    ) -> None:
        self.cache = cache
        self.data_processor = data_processor
        self.lambdas = lambdas_module
        self.writer = writer
        self.result_warehouse = result_warehouse
        self.flow_predictor = flow_predictor
        self.queue_predictor = queue_predictor
        self.dqn_select = dqn_select
        self.coordinate = coordinate
        self.phase_check = phase_check
        self.select_data_to_send = select_data_to_send
        self.is_millisecond_timestamp = is_millisecond_timestamp
        self.overflow_warning_map = overflow_warning_map
        self.radar_event_map = radar_event_map
        self.flow_duration_seconds = flow_duration_seconds
        self.worker_count = worker_count
        self.logger = logger
        self.last_coordinate_set = copy.deepcopy(self.lambdas.map_lambda)

    def run_once(self) -> list[dict[str, Any]]:
        """聚合当前窗口数据，执行路口决策并更新结果仓库。"""
        current_result, online_map, overflow_map = self._process_data()
        action = {
            intersection_id: result["result_action"]
            for intersection_id, result in current_result.items()
        }
        if len(current_result) == len(self.lambdas.intersection_list):
            action = self.coordinate(
                action,
                self.last_coordinate_set,
                online_map,
                overflow_map,
            )
        action, result_check_report = self.phase_check(action)
        self.writer.write_phase_check(result_check_report)

        results_to_send = []
        for intersection_id, result in current_result.items():
            result["result_action"] = action[intersection_id]
            results_to_send.append(
                self.select_data_to_send(
                    intersection_id,
                    action[intersection_id],
                    result["traffic_vector"],
                    result["model_info_list"],
                )
            )
        self.result_warehouse.replace(results_to_send)
        return results_to_send

    def _process_data(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        self.cache.clear_expired()
        recent_data = self.data_processor.snapshot()
        recent_flow_data = recent_data["flow"]
        recent_queue_data = recent_data["queue"]
        recent_stage_data = recent_data["stage"]
        recent_extend_data = recent_data["extend"]
        recent_radar_data = recent_data["radar"]
        recent_boyan_data = recent_data["boyan"]

        self._info("extend_data_cache size: %s", self.cache.size(DataKind.EXTEND))
        intersection_flow, flow_map, intersection_flow_duration2 = self._build_flow_data(
            recent_flow_data
        )
        result_queue_length, queue_map = self._build_queue_data(recent_queue_data)
        stage_map = self._build_optional_data(recent_stage_data, self.data_processor.stage)
        extend_map = self._build_optional_data(recent_extend_data, self.data_processor.extend)
        boyan_map = self._build_optional_data(recent_boyan_data, self.data_processor.boyan)
        radar_map = self._build_optional_data(recent_radar_data, self.data_processor.radar)

        current_flow_prediction = self.flow_predictor.get_current_flow_prediction()
        current_queue_prediction = self.queue_predictor.get_current_queue_prediction()
        online_map = self.data_processor.online()
        overflow_map = self.data_processor.radar_event(
            self.radar_event_map,
            self.overflow_warning_map,
        )

        result_map = copy.deepcopy(self.lambdas.map_lambda)
        new_coordinate_set = copy.deepcopy(self.lambdas.map_lambda)
        with ThreadPoolExecutor(max_workers=self.worker_count) as executor:
            futures = [
                executor.submit(
                    self._process_single_intersection,
                    intersection_id,
                    intersection_flow,
                    result_queue_length,
                    flow_map,
                    queue_map,
                    stage_map,
                    intersection_flow_duration2,
                    current_flow_prediction,
                    current_queue_prediction,
                    extend_map,
                    online_map,
                    overflow_map,
                    radar_map,
                    boyan_map,
                )
                for intersection_id in self.lambdas.intersection_list
            ]
            for future in futures:
                try:
                    intersection_id, result, coordinate_map = future.result()
                    result_map[intersection_id] = result
                    new_coordinate_set[intersection_id] = coordinate_map
                except Exception as error:
                    self._error("Error processing intersection data: %s", error, exc_info=True)

        self.last_coordinate_set = new_coordinate_set
        return result_map, online_map, overflow_map

    def _build_flow_data(self, recent_flow_data: list[dict[str, Any]]):
        if not recent_flow_data:
            intersection_flow = copy.deepcopy(self.lambdas.intersection_flow_lambda)
            return (
                intersection_flow,
                copy.deepcopy(self.lambdas.map_lambda),
                copy.deepcopy(intersection_flow),
            )

        intersection_flow, flow_map = self.data_processor.flow()
        intersection_flow_duration2, _ = self.data_processor.flow_duration(
            self.flow_duration_seconds
        )
        end_time = recent_flow_data[0].get("ts")
        if self.is_millisecond_timestamp(end_time):
            self.writer.write_flow_prediction(
                self.flow_predictor.flow_pre_json_Gen(
                    intersection_flow,
                    intersection_flow_duration2,
                    end_time,
                )
            )
        else:
            self._warning("Flow data has no valid ts; skipped flow prediction output")
        return intersection_flow, flow_map, intersection_flow_duration2

    def _build_queue_data(self, recent_queue_data: list[dict[str, Any]]):
        if not recent_queue_data:
            return (
                copy.deepcopy(self.lambdas.max_lengths_lambda),
                copy.deepcopy(self.lambdas.map_lambda),
            )

        result_queue_length, queue_map = self.data_processor.queue()
        start_time = recent_queue_data[0].get("start_time")
        if self.is_millisecond_timestamp(start_time):
            self.writer.write_queue_prediction(
                self.queue_predictor.queue_pre_json_gen(result_queue_length, start_time)
            )
        else:
            self._warning("Queue data has no valid start_time; skipped queue prediction output")
        return result_queue_length, queue_map

    def _build_optional_data(self, recent_data: list[Any], processor: Callable[[], Any]):
        if recent_data:
            return processor()
        return copy.deepcopy(self.lambdas.map_lambda)

    def _process_single_intersection(
        self,
        intersection_id: str,
        intersection_flow: dict[str, Any],
        result_queue_length: dict[str, Any],
        flow_map: dict[str, Any],
        queue_map: dict[str, Any],
        stage_map: dict[str, Any],
        intersection_flow_duration2: dict[str, Any],
        current_flow_prediction: dict[str, Any],
        current_queue_prediction: dict[str, Any],
        extend_map: dict[str, Any],
        online_map: dict[str, Any],
        overflow_map: dict[str, Any],
        radar_map: dict[str, Any],
        boyan_map: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        result = copy.deepcopy(self.lambdas.intersection_result_lambda)
        traffic_vector = intersection_flow[intersection_id]
        coordinate_map: dict[str, Any] = {}
        try:
            result_action, coordinate_map, model_info_list, exp_list = self.dqn_select(
                traffic_vector,
                result_queue_length[intersection_id],
                intersection_flow_duration2[intersection_id],
                time.time(),
                dict(flow_map[intersection_id]),
                dict(queue_map[intersection_id]),
                dict(stage_map[intersection_id]),
                self.last_coordinate_set,
                current_flow_prediction,
                current_queue_prediction,
                dict(extend_map[intersection_id]),
                dict(overflow_map[intersection_id]),
                dict(radar_map[intersection_id]),
                intersection_id,
                dict(boyan_map[intersection_id]),
            )
            self.writer.write_experience(exp_list, intersection_id)
            result["result_action"] = result_action
            result["traffic_vector"] = traffic_vector
            result["model_info_list"] = model_info_list
            self._info("Intersection %s process result: %s", intersection_id, result)
        except Exception as error:
            self._error("Error getting dqn_%s result: %s", intersection_id, error, exc_info=True)
        return intersection_id, result, coordinate_map

    def _info(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.info(message, *args)

    def _warning(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.warning(message, *args)

    def _error(self, message: str, *args: Any, **kwargs: Any) -> None:
        if self.logger is not None:
            self.logger.error(message, *args, **kwargs)
