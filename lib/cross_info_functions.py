import copy
import os
import threading

from lib._local_json_store import read_json_object, write_json_object


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CROSS_INFO_PATH = os.path.join(BASE_DIR, "cross_info.json")
CODE_CONFIG_PATH = os.path.join(BASE_DIR, "code_config.json")

_DIRECTIONS = ("U", "D", "L", "R")
_GLOBAL_GROUPS = ("aibi_road", "online")
_CROSS_TYPES = ("Radar", "Video")
_write_lock = threading.Lock()


def _normalize_cross_id(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    value = payload.get("Cross_id")
    if value is None or isinstance(value, bool):
        raise ValueError("Cross_id is required")

    cross_id = str(value).strip()
    if not cross_id.isdigit():
        raise ValueError("Cross_id must be numeric")
    return cross_id


def _normalize_key(value, field_name):
    key = str(value).strip()
    if not key:
        raise ValueError(f"{field_name} key must not be empty")
    return key


def _normalize_phase(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("cross_info.phase must be a non-empty JSON object")
    return {
        _normalize_key(key, "cross_info.phase"): copy.deepcopy(direction)
        for key, direction in value.items()
    }


def _normalize_lane_no(value):
    if not isinstance(value, dict):
        raise ValueError("cross_info.LaneNo must be a JSON object")

    normalized = {direction: {} for direction in _DIRECTIONS}
    for direction, lanes in value.items():
        direction_key = str(direction).upper()
        if direction_key not in _DIRECTIONS:
            raise ValueError(f"invalid LaneNo direction: {direction}")
        if lanes in (None, ""):
            lanes = {}
        if not isinstance(lanes, dict):
            raise ValueError(f"cross_info.LaneNo[{direction_key}] must be a JSON object")
        normalized[direction_key] = {
            _normalize_key(key, f"cross_info.LaneNo[{direction_key}]"): copy.deepcopy(lane)
            for key, lane in lanes.items()
        }
    return normalized


def _normalize_jtll(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("cross_info.jtll_ddbh must be a non-empty JSON object")

    normalized = {}
    for detector_id, direction in value.items():
        detector_key = _normalize_key(detector_id, "cross_info.jtll_ddbh")
        if not detector_key.isdigit():
            raise ValueError(
                f"jtll_ddbh detector id must be numeric: {detector_key}"
            )
        direction_key = str(direction).upper()
        if direction_key not in _DIRECTIONS:
            raise ValueError(
                f"jtll_ddbh[{detector_key}] direction must be one of U/D/L/R"
            )
        normalized[detector_key] = direction_key
    return normalized


def _normalize_cycle(value, field_name):
    if not isinstance(value, list) or not value:
        raise ValueError(f"cross_info.{field_name} must be a non-empty list")

    normalized = []
    for index, cycle in enumerate(value):
        if not isinstance(cycle, list) or not cycle:
            raise ValueError(f"cross_info.{field_name}[{index}] must be a non-empty list")
        try:
            normalized.append([int(item) for item in cycle])
        except (TypeError, ValueError):
            raise ValueError(f"cross_info.{field_name}[{index}] must contain integers")
    return normalized


def _normalize_code_config(payload):
    code_config = payload.get("code_config")
    if code_config is None:
        return None
    if not isinstance(code_config, dict):
        raise ValueError("code_config must be a JSON object")

    global_group = str(code_config.get("global_group", "")).strip()
    cross_type = str(code_config.get("cross_type", "")).strip()
    if global_group not in _GLOBAL_GROUPS:
        raise ValueError(
            "code_config.global_group must be one of: " + ", ".join(_GLOBAL_GROUPS)
        )
    if cross_type not in _CROSS_TYPES:
        raise ValueError(
            "code_config.cross_type must be one of: " + ", ".join(_CROSS_TYPES)
        )
    return {"global_group": global_group, "cross_type": cross_type}


def _normalize_cross_info(payload):
    cross_info = payload.get("cross_info")
    if not isinstance(cross_info, dict):
        raise ValueError("cross_info must be a JSON object")

    required = ("phase", "LaneNo", "jtll_ddbh")
    missing = [field for field in required if field not in cross_info]
    if missing:
        raise ValueError("cross_info missing fields: " + ", ".join(missing))

    normalized = {
        "phase": _normalize_phase(cross_info["phase"]),
        "LaneNo": _normalize_lane_no(cross_info["LaneNo"]),
        "jtll_ddbh": _normalize_jtll(cross_info["jtll_ddbh"]),
    }

    # 兼容文档的 zhouqi 与旧文件里的 Cycle，二者等价
    cycle_value = None
    if "zhouqi" in cross_info:
        cycle_value = _normalize_cycle(cross_info["zhouqi"], "zhouqi")
    elif "Cycle" in cross_info:
        cycle_value = _normalize_cycle(cross_info["Cycle"], "Cycle")
    if cycle_value is not None:
        normalized["Cycle"] = cycle_value

    return normalized


def _success(cross_id, operation):
    return {
        "status": "success",
        "saved": True,
        "Cross_id": cross_id,
        "operation": operation,
        "message": "add success" if operation == "created" else "update success",
    }


def _error(reason):
    return {
        "status": "error",
        "saved": False,
        "reason": str(reason),
    }


def _operation(data, cross_id):
    return "updated" if cross_id in data else "created"


def _items(cross_id, dry_run, files):
    return [{
        "cross_id": cross_id,
        "saved": not dry_run,
        "files": {
            name: {"path": path, "operation": operation}
            for name, (path, operation) in files.items()
        },
        "code_changes": {
            "Lambdas.py": [],
            "Global_intersection_coordinate.py": [],
            "DQN_Select.py": [],
        },
    }]


def query_cross_info(payload):
    try:
        cross_id = _normalize_cross_id(payload)
        data = read_json_object(CROSS_INFO_PATH)
        return copy.deepcopy(data.get(cross_id, {}))
    except Exception:
        return {}


def list_cross_infos(full=False):
    data = read_json_object(CROSS_INFO_PATH)
    if full:
        return {"status": "success", "count": len(data), "items": copy.deepcopy(data)}
    return {"status": "success", "count": len(data), "items": sorted(data)}


def validate_and_save_cross_info(payload, dry_run=False):
    try:
        cross_id = _normalize_cross_id(payload)
        cross_info = _normalize_cross_info(payload)
        code_config = _normalize_code_config(payload)

        with _write_lock:
            data = read_json_object(CROSS_INFO_PATH)
            operation = _operation(data, cross_id)
            files = {"cross_info.json": ("lib/cross_info.json", operation)}

            if not dry_run:
                data[cross_id] = cross_info
                write_json_object(CROSS_INFO_PATH, data)

                if code_config is not None:
                    code_data = read_json_object(CODE_CONFIG_PATH)
                    code_data[cross_id] = code_config
                    write_json_object(CODE_CONFIG_PATH, code_data)
                    files["code_config.json"] = ("lib/code_config.json", "updated")

        return {
            "status": "validated" if dry_run else "success",
            "saved": not dry_run,
            "Cross_id": cross_id,
            "message": "validation success" if dry_run else "save success",
            "items": _items(cross_id, dry_run, files),
        }
    except Exception as error:
        return _error(error)


def add_cross_info(payload):
    try:
        cross_id = _normalize_cross_id(payload)
        cross_info = _normalize_cross_info(payload)

        with _write_lock:
            data = read_json_object(CROSS_INFO_PATH)
            if cross_id in data:
                raise ValueError(f"Cross_id {cross_id} already exists")
            data[cross_id] = cross_info
            write_json_object(CROSS_INFO_PATH, data)

        return _success(cross_id, "created")
    except Exception as error:
        return _error(error)


def update_cross_info(payload):
    try:
        cross_id = _normalize_cross_id(payload)
        cross_info = _normalize_cross_info(payload)

        with _write_lock:
            data = read_json_object(CROSS_INFO_PATH)
            if cross_id not in data:
                raise ValueError(f"Cross_id {cross_id} does not exist")
            data[cross_id] = cross_info
            write_json_object(CROSS_INFO_PATH, data)

        return _success(cross_id, "updated")
    except Exception as error:
        return _error(error)


def delete_cross_info(cross_id, dry_run=False, delete_code=True):
    try:
        cross_id = str(cross_id).strip()
        if not cross_id.isdigit():
            raise ValueError("Cross_id must be numeric")

        with _write_lock:
            data = read_json_object(CROSS_INFO_PATH)
            existed = cross_id in data
            if existed and not dry_run:
                del data[cross_id]
                write_json_object(CROSS_INFO_PATH, data)

            code_existed = False
            if delete_code:
                code_data = read_json_object(CODE_CONFIG_PATH)
                code_existed = cross_id in code_data
                if code_existed and not dry_run:
                    del code_data[cross_id]
                    write_json_object(CODE_CONFIG_PATH, code_data)

        return {
            "status": "validated" if dry_run else "success",
            "saved": not dry_run,
            "deleted": existed,
            "code_deleted": code_existed,
            "Cross_id": cross_id,
        }
    except Exception as error:
        return _error(error)
