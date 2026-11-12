import logging
from Lambdas import intersection_list
import copy
import json
import math
import os
import tempfile
import threading
from pathlib import Path
# -*- coding: utf-8 -*-

from app.paths import INTERSECTION_RESULT_CONFIG_PATH as INTERSECTION_CONFIG_PATH
_config_lock = threading.RLock()


def validate_intersection_result_config(data):
    if not isinstance(data, dict) or not data:
        raise ValueError("intersection result config must be a non-empty object")

    normalized = {}
    for raw_intersection_id, raw_plans in data.items():
        intersection_id = str(raw_intersection_id)
        if not intersection_id.isdigit():
            raise ValueError(f"invalid intersection ID: {intersection_id}")
        if not isinstance(raw_plans, dict) or not raw_plans:
            raise ValueError(
                f"intersection {intersection_id} must contain at least one plan"
            )

        plans = {}
        for raw_plan_id, raw_phases in raw_plans.items():
            plan_id = str(raw_plan_id)
            if not plan_id.isdigit():
                raise ValueError(
                    f"invalid plan ID {plan_id} for intersection {intersection_id}"
                )
            if not isinstance(raw_phases, dict) or not raw_phases:
                raise ValueError(
                    f"plan {plan_id} for intersection {intersection_id} "
                    "must contain at least one phase"
                )

            phases = {}
            for raw_phase_id, raw_range in raw_phases.items():
                phase_id = str(raw_phase_id)
                if not phase_id.isdigit() or not 0 <= int(phase_id) <= 8:
                    raise ValueError(
                        f"invalid phase ID {phase_id} for intersection "
                        f"{intersection_id}, plan {plan_id}"
                    )
                if not isinstance(raw_range, list) or len(raw_range) != 2:
                    raise ValueError(
                        f"phase {phase_id} range for intersection {intersection_id}, "
                        f"plan {plan_id} must be [min, max]"
                    )

                min_value, max_value = raw_range
                for value in (min_value, max_value):
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                    ):
                        raise ValueError(
                            f"phase {phase_id} range for intersection "
                            f"{intersection_id}, plan {plan_id} must be numeric"
                        )
                if min_value > max_value:
                    raise ValueError(
                        f"phase {phase_id} range for intersection {intersection_id}, "
                        f"plan {plan_id} has min greater than max"
                    )
                phases[phase_id] = [min_value, max_value]
            plans[plan_id] = phases
        normalized[intersection_id] = plans

    return normalized


def load_intersection_result_config(path=INTERSECTION_CONFIG_PATH):
    with open(path, "r", encoding="utf-8-sig") as config_file:
        return validate_intersection_result_config(json.load(config_file))


def get_intersection_result_config():
    with _config_lock:
        return intersection_result_config


def replace_intersection_result_config(data, path=INTERSECTION_CONFIG_PATH):
    global intersection_result_config

    normalized = validate_intersection_result_config(data)
    target_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(target_dir, exist_ok=True)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target_dir,
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            json.dump(normalized, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
            os.chmod(temp_file.name, 0o644)
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    with _config_lock:
        intersection_result_config = normalized
    return normalized


intersection_result_config = load_intersection_result_config()

_ROAD_INFO_CACHE = {"signature": None, "data": {}}


def _load_road_info_config():
    from app.paths import ROAD_INFO_PATH

    path = Path(ROAD_INFO_PATH)
    try:
        stat = path.stat()
    except OSError:
        return {}
    signature = (stat.st_mtime_ns, stat.st_size)
    if signature != _ROAD_INFO_CACHE["signature"]:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError:
            data = {}
        _ROAD_INFO_CACHE["data"] = data if isinstance(data, dict) else {}
        _ROAD_INFO_CACHE["signature"] = signature
    return _ROAD_INFO_CACHE["data"]


def _road_info_plan_rules(inter_id, plan_id):
    """用 road_info 的 min/max 兜底生成安全规则（Nacos 配置优先）。"""
    states = _load_road_info_config().get(str(inter_id))
    if not isinstance(states, dict):
        return None
    state = states.get(str(plan_id))
    if not isinstance(state, dict):
        return None
    phases = state.get("phase") or []
    minimums = state.get("min_pass_time") or []
    maximums = state.get("max_pass_time") or []
    rules = {}
    for index, phase in enumerate(phases[:9]):
        if not phase:
            continue
        low = int(minimums[index]) if index < len(minimums) else 0
        high = int(maximums[index]) if index < len(maximums) else 0
        if high < low:
            high = low
        rules[str(index)] = [low, high]
    return rules or None


def phase_check(current_result, *, config_snapshot=None):
    """
    适配平铺字典格式的数据校验
    输入格式: { "路口ID": [相位1, 相位2, ..., 相位9, 方案号] }
    """
    report = {}
    if config_snapshot is None:
        config_snapshot = get_intersection_result_config()

    for inter_id, phase_list in current_result.items():
        # 初始化当前路口的报告状态
        res = {
            "check_status": 0, 
            "msg": "OK",
            "modifications": []
        }

        # 1. 先提取方案号（数组第10位，即索引9）
        # 使用 int() 转换是为了防止 0.0 这种浮点数导致 Key 匹配失败
        try:
            plan_id = str(int(phase_list[9]))
        except (IndexError, ValueError):
            res["check_status"] = 2
            res["msg"] = "Invalid plan ID format"
            report[inter_id] = res
            continue

        # 2. 空方案直接判无效，交给安全门走时刻表兜底，避免下发全零相位
        if not any(value != 0 for value in phase_list[:8]):
            res["check_status"] = 2
            res["msg"] = "Empty phase plan"
            report[inter_id] = res
            continue

        # 3. 优先用 Nacos 配置；缺失时用 road_info 的 min/max 兜底
        plan_rules = None
        if inter_id in config_snapshot:
            plan_rules = config_snapshot[inter_id].get(plan_id)
        if not plan_rules:
            plan_rules = _road_info_plan_rules(inter_id, plan_id)
            if plan_rules:
                res["msg"] = "OK (road_info fallback)"

        # 3. 两边都没有才报缺失
        if not plan_rules:
            if inter_id not in config_snapshot:
                res["check_status"] = 1
                res["msg"] = "Intersection missing in config"
            else:
                res["check_status"] = 2
                res["msg"] = f"Plan {plan_id} not found for this intersection"
            report[inter_id] = res
            continue

        # 4. 校验前 9 个相位时长
        for i in range(9):
            val = phase_list[i]
            
            # 逻辑：遇到 0 则停止后续相位校验
            if val == 0:
                break
            
            phase_key = str(i)
            if phase_key in plan_rules:
                min_val, max_val = plan_rules[phase_key]
                
                # 边界检查与原地修正 (支持浮点数比较)
                if val < min_val:
                    phase_list[i] = min_val
                    res["modifications"].append(f"Phase {i}: {val} -> {min_val}")
                elif val > max_val:
                    phase_list[i] = max_val
                    res["modifications"].append(f"Phase {i}: {val} -> {max_val}")

        report[inter_id] = res

    # 返回修改后的数据字典和详细报告
    return current_result, report

phase_check_report={
    intersection_id:{
        ## check_status:
        ## -1 : invalid/error
        ##  0 : checked/valid
        ##  1 : unchecked：
        
        ## phase_no:
        ## -1 : invalid/error
        ##  0 : valid
        
        ## phase_len:
        ## -1 : invalid/error
        ## 0 : valid
        
        ## phase_duration:
        ## -1 : invalid/error
        ## 0 : valid
        ## 1 : adjusted
        
        "intersection_id": intersection_id,
        "check_status": 0,
        "phase_no": 0,
        "phase_len": 0,
        "phase_duration": 0,
    }for intersection_id in intersection_list
}.copy()

def phase_adjust(current_result,report):
  
    return current_result
