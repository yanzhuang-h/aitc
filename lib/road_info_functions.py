import copy
import os
import threading

from lib._local_json_store import read_json_object, write_json_object


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROAD_INFO_PATH = os.path.join(BASE_DIR, "road_info.json")

_ROAD_STATE_FIELDS = (
    "phase",
    "max_pass_time",
    "min_pass_time",
    "platform_max_pass_time",
    "platform_min_pass_time",
    "phase_weight",
)
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


def _normalize_len10(values, field_name):
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list")
    if len(values) > 10:
        raise ValueError(f"{field_name} length must be <= 10")
    return copy.deepcopy(values) + [0] * (10 - len(values))


def _normalize_road_info(payload):
    road_info = payload.get("road_info")
    if not isinstance(road_info, dict) or not road_info:
        raise ValueError("road_info must be a non-empty JSON object")

    normalized = {}
    for state, state_config in road_info.items():
        state_key = str(state).strip()
        if not state_key:
            raise ValueError("road_info state key must not be empty")
        if not isinstance(state_config, dict):
            raise ValueError(f"road_info[{state_key}] must be a JSON object")

        normalized_state = {}
        for field in _ROAD_STATE_FIELDS:
            if field not in state_config:
                raise ValueError(f"road_info[{state_key}] missing field: {field}")
            normalized_state[field] = _normalize_len10(
                state_config[field],
                f"road_info[{state_key}].{field}",
            )
        normalized[state_key] = normalized_state

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


def query_road_info(payload):
    try:
        cross_id = _normalize_cross_id(payload)
        data = read_json_object(ROAD_INFO_PATH)
        return copy.deepcopy(data.get(cross_id, {}))
    except Exception:
        return {}


def list_road_infos(full=False):
    data = read_json_object(ROAD_INFO_PATH)
    if full:
        return {"status": "success", "count": len(data), "items": copy.deepcopy(data)}
    return {"status": "success", "count": len(data), "items": sorted(data)}


def validate_and_save_road_info(payload, dry_run=False):
    try:
        cross_id = _normalize_cross_id(payload)
        road_info = _normalize_road_info(payload)

        with _write_lock:
            data = read_json_object(ROAD_INFO_PATH)
            operation = "updated" if cross_id in data else "created"
            if not dry_run:
                data[cross_id] = road_info
                write_json_object(ROAD_INFO_PATH, data)

        return {
            "status": "validated" if dry_run else "success",
            "saved": not dry_run,
            "Cross_id": cross_id,
            "message": "validation success" if dry_run else "save success",
            "items": [{
                "Cross_id": cross_id,
                "saved": not dry_run,
                "file": {"path": "lib/road_info.json", "operation": operation},
            }],
        }
    except Exception as error:
        return _error(error)


def add_road_info(payload):
    try:
        cross_id = _normalize_cross_id(payload)
        road_info = _normalize_road_info(payload)

        with _write_lock:
            data = read_json_object(ROAD_INFO_PATH)
            if cross_id in data:
                raise ValueError(f"Cross_id {cross_id} already exists")
            data[cross_id] = road_info
            write_json_object(ROAD_INFO_PATH, data)

        return _success(cross_id, "created")
    except Exception as error:
        return _error(error)


def update_road_info(payload):
    try:
        cross_id = _normalize_cross_id(payload)
        road_info = _normalize_road_info(payload)

        with _write_lock:
            data = read_json_object(ROAD_INFO_PATH)
            if cross_id not in data:
                raise ValueError(f"Cross_id {cross_id} does not exist")
            data[cross_id] = road_info
            write_json_object(ROAD_INFO_PATH, data)

        return _success(cross_id, "updated")
    except Exception as error:
        return _error(error)


def delete_road_info(cross_id, dry_run=False):
    try:
        cross_id = str(cross_id).strip()
        if not cross_id.isdigit():
            raise ValueError("Cross_id must be numeric")

        with _write_lock:
            data = read_json_object(ROAD_INFO_PATH)
            existed = cross_id in data
            if existed and not dry_run:
                del data[cross_id]
                write_json_object(ROAD_INFO_PATH, data)

        return {
            "status": "validated" if dry_run else "success",
            "saved": not dry_run,
            "deleted": existed,
            "Cross_id": cross_id,
        }
    except Exception as error:
        return _error(error)
