import copy
import json
import os
import tempfile
import threading
import time


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROAD_STATE_PATH = os.path.join(BASE_DIR, "road_state.json")
ROAD_INFO_PATH = os.path.join(BASE_DIR, "road_info.json")

_cache_mtime = None
_cache_data = {}
_write_lock = threading.Lock()


def _load_road_state(path=ROAD_STATE_PATH):
    global _cache_mtime, _cache_data

    if not os.path.exists(path):
        _cache_mtime = None
        _cache_data = {}
        return _cache_data

    mtime = os.path.getmtime(path)
    if _cache_mtime == mtime:
        return _cache_data

    with open(path, "r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        data = {}

    _cache_mtime = mtime
    _cache_data = data
    return _cache_data


def _normalize_key(value):
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value).strip()


def _normalize_state_key(value):
    if isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    return _normalize_key(value)


def _get_rule_value(rule, *keys):
    for key in keys:
        if key in rule:
            return rule[key]
    return None


def _normalize_time_value(value):
    raw_value = str(value).strip().replace("\uff1a", ":")
    parts = raw_value.split(":")
    if len(parts) != 2:
        raise ValueError(f"time value must use HH:MM format: {raw_value}")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        raise ValueError(f"time value must use numeric HH:MM format: {raw_value}")

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"time value is out of range: {raw_value}")

    normalized = f"{hour:02d}:{minute:02d}"
    return normalized, hour * 60 + minute


def _minutes_to_time(minutes):
    minutes = int(minutes)
    hour = minutes // 60
    minute = minutes % 60
    return f"{hour:02d}:{minute:02d}"


def _current_time_slot(current_time=None):
    if current_time is None:
        local_time = time.localtime()
    elif isinstance(current_time, time.struct_time):
        local_time = current_time
    else:
        timestamp = float(current_time)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        local_time = time.localtime(timestamp)

    normalized = f"{local_time.tm_hour:02d}:{local_time.tm_min:02d}"
    return normalized, local_time.tm_hour * 60 + local_time.tm_min


def _is_time_in_range(now_minutes, start_minutes, end_minutes):
    if start_minutes <= end_minutes:
        return start_minutes <= now_minutes <= end_minutes
    return now_minutes >= start_minutes or now_minutes <= end_minutes


def _iter_rules(raw_rules):
    if isinstance(raw_rules, dict):
        return [raw_rules]
    if isinstance(raw_rules, list):
        return [rule for rule in raw_rules if isinstance(rule, dict)]
    return []


def _read_road_state_uncached(path=ROAD_STATE_PATH):
    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("road_state.json must contain a JSON object")

    return data


def _save_road_state(data, path=ROAD_STATE_PATH):
    global _cache_mtime, _cache_data

    target_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(target_dir, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target_dir,
        delete=False,
    ) as temp_file:
        temp_path = temp_file.name
        json.dump(data, temp_file, ensure_ascii=False, indent=4)
        temp_file.write("\n")
        temp_file.flush()
        os.fsync(temp_file.fileno())

    os.replace(temp_path, path)
    _cache_mtime = None
    _cache_data = {}


def _load_road_info(path=ROAD_INFO_PATH):
    with open(path, "r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("road_info.json must contain a JSON object")

    return data


def _normalize_enabled(value):
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off"}
    return bool(value)


def _rule_time_minutes(rule):
    start_raw = _get_rule_value(rule, "Start_time", "start_time", "start")
    end_raw = _get_rule_value(rule, "end_time", "End_time", "end")
    start_slot, start_minutes = _normalize_time_value(start_raw)
    end_slot, end_minutes = _normalize_time_value(end_raw)
    return start_slot, start_minutes, end_slot, end_minutes


def _copy_rule_with_range(rule, start_minutes, end_minutes):
    copied = copy.deepcopy(rule)
    copied["Start_time"] = _minutes_to_time(start_minutes)
    copied["end_time"] = _minutes_to_time(end_minutes)
    return copied


def _upsert_time_range_rule(rules, new_rule):
    _, new_start, _, new_end = _rule_time_minutes(new_rule)

    if new_start > new_end:
        new_rules = [rule for rule in rules if isinstance(rule, dict)]
        new_rules.append(copy.deepcopy(new_rule))
        return new_rules, []

    updated_rules = []
    affected_rules = []

    for old_rule in rules:
        if not isinstance(old_rule, dict):
            continue

        try:
            _, old_start, _, old_end = _rule_time_minutes(old_rule)
        except Exception:
            updated_rules.append(old_rule)
            continue

        if old_start > old_end:
            updated_rules.append(old_rule)
            continue

        if old_end < new_start or old_start > new_end:
            updated_rules.append(old_rule)
            continue

        affected_rules.append(copy.deepcopy(old_rule))

        if old_start < new_start:
            updated_rules.append(_copy_rule_with_range(old_rule, old_start, new_start - 1))

        if old_end > new_end:
            updated_rules.append(_copy_rule_with_range(old_rule, new_end + 1, old_end))

    updated_rules.append(copy.deepcopy(new_rule))
    updated_rules.sort(key=lambda rule: _rule_time_minutes(rule)[1])
    return updated_rules, affected_rules


def _normalize_update_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    cross_raw = _get_rule_value(payload, "Cross_id", "cross_id", "id")
    start_raw = _get_rule_value(payload, "Start_time", "start_time", "start")
    end_raw = _get_rule_value(payload, "end_time", "End_time", "end")
    state_raw = _get_rule_value(payload, "zhuangtai", "state", "State")

    if cross_raw is None:
        raise ValueError("missing required payload field: Cross_id")
    if start_raw is None:
        raise ValueError("missing required payload field: Start_time")
    if end_raw is None:
        raise ValueError("missing required payload field: end_time")
    if state_raw is None:
        raise ValueError("missing required payload field: zhuangtai")

    start_slot, _ = _normalize_time_value(start_raw)
    end_slot, _ = _normalize_time_value(end_raw)

    return {
        "cross_id": _normalize_key(cross_raw),
        "Start_time": start_slot,
        "end_time": end_slot,
        "zhuangtai": int(_normalize_state_key(state_raw)),
        "enabled": _normalize_enabled(payload.get("enabled", True)),
    }


def validate_road_state_update(payload, road_info_path=ROAD_INFO_PATH):
    rule = _normalize_update_payload(payload)
    road_info = _load_road_info(road_info_path)
    cross_id = rule["cross_id"]
    state = str(rule["zhuangtai"])

    if cross_id not in road_info:
        return {
            "status": "error",
            "saved": False,
            "reason": f"路口{cross_id}不存在，添加失败",
            "rule": rule,
        }

    if state not in road_info[cross_id]:
        return {
            "status": "error",
            "saved": False,
            "reason": f"路口{cross_id}不存在状态{state}信息，添加失败",
            "rule": rule,
        }

    return {
        "status": "valid",
        "saved": False,
        "message": "validation success",
        "rule": rule,
    }


def validate_and_save_road_state(
    payload,
    path=ROAD_STATE_PATH,
    road_info_path=ROAD_INFO_PATH,
    dry_run=False,
):
    try:
        validation = validate_road_state_update(payload, road_info_path=road_info_path)
        if validation["status"] == "error":
            return validation

        rule = validation["rule"]
        if dry_run:
            return {
                "status": "validated",
                "saved": False,
                "message": "validation success",
                "rule": rule,
            }

        with _write_lock:
            data = _read_road_state_uncached(path)
            rules = data.setdefault(rule["cross_id"], [])
            if isinstance(rules, dict):
                rules = [rules]
            if not isinstance(rules, list):
                rules = []

            stored_rule = {key: value for key, value in rule.items() if key != "cross_id"}
            rules, affected_rules = _upsert_time_range_rule(rules, stored_rule)
            data[rule["cross_id"]] = rules
            _save_road_state(data, path)

        return {
            "status": "success",
            "saved": True,
            "message": "save success",
            "operation": "updated" if affected_rules else "created",
            "before": affected_rules,
            "after": rule,
            "rules": rules,
        }
    except Exception as error:
        return {
            "status": "error",
            "saved": False,
            "reason": str(error),
        }


def get_road_state_config(path=ROAD_STATE_PATH):
    return copy.deepcopy(_load_road_state(path))


def validate_road_state_config(data, road_info_path=ROAD_INFO_PATH):
    if not isinstance(data, dict):
        raise ValueError("road_state.json must contain a JSON object")

    road_info = _load_road_info(road_info_path)
    normalized = {}

    for raw_cross_id, raw_rules in data.items():
        cross_id = _normalize_key(raw_cross_id)
        if cross_id in normalized:
            raise ValueError(f"duplicate normalized Cross_id: {cross_id}")
        if cross_id not in road_info:
            raise ValueError(f"Cross_id {cross_id} is not in road_info")

        if isinstance(raw_rules, dict):
            raw_rules = [raw_rules]
        if not isinstance(raw_rules, list):
            raise ValueError(f"road_state[{cross_id}] must be an object or array")

        normalized_rules = []
        for rule_index, raw_rule in enumerate(raw_rules):
            if not isinstance(raw_rule, dict):
                raise ValueError(
                    f"road_state[{cross_id}][{rule_index}] must be a JSON object"
                )

            payload = copy.deepcopy(raw_rule)
            payload["Cross_id"] = cross_id
            rule = _normalize_update_payload(payload)
            state = str(rule["zhuangtai"])
            if state not in road_info[cross_id]:
                raise ValueError(
                    f"zhuangtai {state} is not in road_info[{cross_id}]"
                )

            normalized_rules.append({
                "Start_time": rule["Start_time"],
                "end_time": rule["end_time"],
                "zhuangtai": rule["zhuangtai"],
                "enabled": rule["enabled"],
            })

        normalized[cross_id] = normalized_rules

    return normalized


def replace_road_state_config(
    data,
    path=ROAD_STATE_PATH,
    road_info_path=ROAD_INFO_PATH,
):
    normalized = validate_road_state_config(
        data,
        road_info_path=road_info_path,
    )
    with _write_lock:
        _save_road_state(normalized, path)
    return copy.deepcopy(normalized)


def get_forced_state(cross_id, current_state, road_info, current_time=None, path=ROAD_STATE_PATH):
    current_state = _normalize_state_key(current_state)
    cross_id = _normalize_key(cross_id)
    state_data = _load_road_state(path)
    raw_rules = state_data.get(cross_id)
    if not raw_rules:
        return current_state, None

    now_slot, now_minutes = _current_time_slot(current_time)

    for rule_index, rule in enumerate(_iter_rules(raw_rules)):
        if not rule.get("enabled", True):
            continue

        try:
            start_raw = _get_rule_value(rule, "Start_time", "start_time", "start")
            end_raw = _get_rule_value(rule, "end_time", "End_time", "end")
            state_raw = _get_rule_value(rule, "zhuangtai", "state", "State")
            if start_raw is None or end_raw is None or state_raw is None:
                raise ValueError("missing Start_time/end_time/zhuangtai")

            start_slot, start_minutes = _normalize_time_value(start_raw)
            end_slot, end_minutes = _normalize_time_value(end_raw)
            forced_state = _normalize_state_key(state_raw)
        except Exception as error:
            return current_state, {
                "forced": False,
                "cross_id": cross_id,
                "time": now_slot,
                "rule_index": rule_index,
                "reason": str(error),
                "rule": copy.deepcopy(rule),
            }

        if not _is_time_in_range(now_minutes, start_minutes, end_minutes):
            continue

        if cross_id not in road_info:
            return current_state, {
                "forced": False,
                "cross_id": cross_id,
                "time": now_slot,
                "rule_index": rule_index,
                "reason": f"Cross_id {cross_id} is not in road_info",
            }

        if forced_state not in road_info[cross_id]:
            return current_state, {
                "forced": False,
                "cross_id": cross_id,
                "time": now_slot,
                "rule_index": rule_index,
                "reason": f"zhuangtai {forced_state} is not in road_info[{cross_id}]",
                "before": current_state,
                "after": forced_state,
                "start": start_slot,
                "end": end_slot,
            }

        return forced_state, {
            "forced": True,
            "cross_id": cross_id,
            "time": now_slot,
            "rule_index": rule_index,
            "before": current_state,
            "after": forced_state,
            "start": start_slot,
            "end": end_slot,
        }

    return current_state, None
