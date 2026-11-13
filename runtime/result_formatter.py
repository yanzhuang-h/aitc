"""将周期决策结果转换为下游控制协议。"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

from app.core.models import DecisionResult
from lib.road_groups import TONGZHOU_49

_PLAN_OVERRIDES_PATH = Path(__file__).resolve().parents[1] / "lib" / "plan_id_overrides.json"
_PLAN_OVERRIDES_CACHE = {"signature": None, "data": {}}


def _plan_id_for(intersection_id: str, default: Any) -> Any:
    """按路口覆盖对外 programID（平台方案号从 1 开始）。"""
    # 通州适配器已输出真实平台方案号；上线时的固定覆盖不能将强制方案的相位
    # 错标成另一个方案。零值候选仍沿用原有兜底方案号。
    if str(intersection_id) in TONGZHOU_49 and type(default) is int and default > 0:
        return default
    try:
        stat = _PLAN_OVERRIDES_PATH.stat()
    except OSError:
        return default
    signature = (stat.st_mtime_ns, stat.st_size)
    if signature != _PLAN_OVERRIDES_CACHE["signature"]:
        try:
            data = json.loads(_PLAN_OVERRIDES_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        _PLAN_OVERRIDES_CACHE["data"] = data if isinstance(data, dict) else {}
        _PLAN_OVERRIDES_CACHE["signature"] = signature
    overrides = _PLAN_OVERRIDES_CACHE["data"]
    return overrides.get(str(intersection_id), default)


def _empty_plan_timetable_fallback(intersection_id: str, result_to_send: list[Any]) -> list[Any]:
    """已配置平台方案号的新路口，如果相位全零，用时刻表填充后再下发。"""
    if any(value != 0 for value in result_to_send[:8]):
        return result_to_send
    if _plan_id_for(intersection_id, None) is None:
        return result_to_send
    try:
        from datetime import datetime

        from lib.AITC_tool import Get_time_map

        schedule = Get_time_map(intersection_id)
        if not isinstance(schedule, dict):
            return result_to_send
        vector = schedule.get(str(datetime.now().hour)) or next(iter(schedule.values()), None)
        if vector is None:
            return result_to_send
        fallback = [int(value) for value in list(vector)[:10]]
        while len(fallback) < 10:
            fallback.append(0)
        if any(fallback[:8]):
            fallback[9] = result_to_send[9]
            return fallback
    except Exception:
        return result_to_send
    return result_to_send


def format_result(
    intersection_id: str,
    result_to_send: list[Any],
    traffic_vector: list[Any],
    model_info_list: list[Any],
    *,
    lambdas_module: Any,
) -> dict[str, Any]:
    """保持既有报文结构，将单路口决策格式化为发送结果。"""
    result_to_send = _empty_plan_timetable_fallback(intersection_id, result_to_send)
    payload = {
        "additional": {
            "tlLogic": {
                "id": intersection_id,
                "type": "NoType",
                "programID": _plan_id_for(intersection_id, result_to_send[9]),
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
