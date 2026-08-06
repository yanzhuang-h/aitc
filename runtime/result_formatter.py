"""将周期决策结果转换为下游控制协议。"""

from __future__ import annotations

import copy
import random
from typing import Any

from app.core.models import DecisionResult


def format_result(
    intersection_id: str,
    result_to_send: list[Any],
    traffic_vector: list[Any],
    model_info_list: list[Any],
    *,
    lambdas_module: Any,
) -> dict[str, Any]:
    """保持既有报文结构，将单路口决策格式化为发送结果。"""
    payload = {
        "additional": {
            "tlLogic": {
                "id": intersection_id,
                "type": "NoType",
                "programID": result_to_send[9],
                "phase": build_phase(result_to_send),
            }
        },
        "traffic_vector": build_traffic_vector(
            traffic_vector,
            intersection_id,
            lambdas_module=lambdas_module,
        ),
        "modelInfo": build_model_info(model_info_list, intersection_id),
    }
    return DecisionResult.from_payload(payload).to_payload()


def build_phase(result_to_send: list[Any]) -> list[dict[str, Any]]:
    """提取有效相位时长，遇到结束标记 0 后停止。"""
    phase = []
    for action in result_to_send:
        if action == 0:
            break
        phase.append({"duration": action})
    return phase


def build_traffic_vector(
    traffic_vector: list[Any],
    intersection_id: str,
    *,
    lambdas_module: Any,
) -> list[dict[str, Any]]:
    """将 LRUD 流量向量映射回原始道路编号。"""
    location_to_road = {
        location: road_id
        for road_id, location in copy.deepcopy(
            lambdas_module.location_to_intersection_lambda
        ).items()
    }
    directions = ("L", "R", "U", "D")
    traffic_data = []
    for index, flow in enumerate(traffic_vector[: len(directions)]):
        road_id = location_to_road.get((intersection_id, directions[index]))
        if road_id is not None:
            traffic_data.append({"id": road_id, "flow": flow})
    return traffic_data


def build_model_info(model_info_list: list[Any], intersection_id: str) -> dict[str, Any]:
    """保持既有模型信息字段及缺省值策略。"""
    if not model_info_list:
        return {
            "crossID": intersection_id,
            "acc": 95,
            "r": 0,
            "rt": 10,
            "score": random.randint(85, 100),
            "pdf": 50,
            "pdq": 50,
            "pds": 50,
            "pd": 600,
        }
    return {
        "crossID": intersection_id,
        "acc": model_info_list[0],
        "r": model_info_list[1],
        "rt": model_info_list[2],
        "score": model_info_list[3],
        "pdf": model_info_list[4],
        "pdq": model_info_list[5],
        "pds": model_info_list[6],
        "pd": model_info_list[7],
    }
