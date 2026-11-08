"""路口时段方案配置接口（工作日 / 周末兜底方案）。

对应文档「流量路口配置接口信息」中的 intersection_schedule 部分：
    GET    /intersection_schedule/{Cross_id}?day_type=workday|weekend
    POST   /intersection_schedule/validate
    POST   /intersection_schedule/update
    POST   /intersection_schedule/delete
    DELETE /intersection_schedule/{Cross_id}?day_type=...&dry_run=true
"""

import copy
import json
import os
import tempfile

from time_schedule.nacos_schedule_config import (
    SCHEDULE_DIR,
    WEEKEND_PREFIX,
    WORKDAY_PREFIX,
)


DAY_TYPES = ("workday", "weekend")


def _normalize_cross_id(value):
    if value is None or isinstance(value, bool):
        raise ValueError("Cross_id is required")
    cross_id = str(value).strip()
    if not cross_id.isdigit():
        raise ValueError("Cross_id must be numeric")
    return cross_id


def _normalize_day_type(value):
    day_type = str(value or "workday").strip().lower()
    if day_type not in DAY_TYPES:
        raise ValueError("day_type must be workday or weekend")
    return day_type


def _normalize_schedule(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("schedule must be a non-empty JSON object")

    normalized = {}
    for raw_hour, raw_values in value.items():
        hour = str(raw_hour).strip()
        if not hour.isdigit() or not 0 <= int(hour) <= 23:
            raise ValueError(f"schedule contains invalid hour: {hour}")
        if not isinstance(raw_values, list):
            raise ValueError(f"schedule hour {hour} must be a list")
        if len(raw_values) > 10:
            raise ValueError(f"schedule hour {hour} length must be <= 10")

        values = []
        for index, item in enumerate(raw_values):
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ValueError(
                    f"schedule hour {hour} value {index} must be a number"
                )
            if item < 0:
                raise ValueError(
                    f"schedule hour {hour} value {index} must be non-negative"
                )
            values.append(item)
        normalized[hour] = values + [0] * (10 - len(values))

    return dict(sorted(normalized.items(), key=lambda item: int(item[0])))


def schedule_path(cross_id, day_type):
    prefix = WEEKEND_PREFIX if day_type == "weekend" else WORKDAY_PREFIX
    return os.path.join(str(SCHEDULE_DIR), f"{prefix}{cross_id}.json")


def _read_schedule(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{os.path.basename(path)} must contain a JSON object")
    return data


def _write_schedule(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False
        ) as file:
            temp_path = file.name
            json.dump(data, file, ensure_ascii=False, indent=4)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
            os.chmod(file.name, 0o644)
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _file_label(path):
    project_root = os.path.dirname(os.path.dirname(str(SCHEDULE_DIR)))
    return os.path.relpath(str(path), project_root).replace(os.sep, "/")


def _success(cross_id, day_type, path, operation, dry_run):
    status = "validated" if dry_run else "success"
    return {
        "status": status,
        "saved": not dry_run,
        "message": "validation success" if dry_run else "save success",
        "Cross_id": cross_id,
        "day_type": day_type,
        "file": _file_label(path),
        "operation": operation,
    }


def _error(reason, dry_run=False):
    return {
        "status": "error",
        "saved": False,
        "dry_run": dry_run,
        "reason": str(reason),
    }


def query_schedule(cross_id, day_type="workday"):
    cross_id = _normalize_cross_id(cross_id)
    day_type = _normalize_day_type(day_type)
    path = schedule_path(cross_id, day_type)
    return {
        "Cross_id": cross_id,
        "day_type": day_type,
        "file": _file_label(path),
        "schedule": copy.deepcopy(_read_schedule(path)),
    }


def list_schedules():
    items = []
    directory = str(SCHEDULE_DIR)
    if not os.path.isdir(directory):
        return items
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        if name.startswith(WEEKEND_PREFIX):
            cross_id = name[len(WEEKEND_PREFIX):-len(".json")]
            day_type = "weekend"
        elif name.startswith(WORKDAY_PREFIX):
            cross_id = name[len(WORKDAY_PREFIX):-len(".json")]
            day_type = "workday"
        else:
            continue
        if not cross_id.isdigit():
            continue
        items.append({
            "Cross_id": cross_id,
            "day_type": day_type,
            "file": _file_label(os.path.join(directory, name)),
        })
    return items


def validate_and_save_schedule(payload, dry_run=False):
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        cross_id = _normalize_cross_id(payload.get("Cross_id"))
        day_type = _normalize_day_type(payload.get("day_type"))
        schedule = _normalize_schedule(payload.get("schedule"))

        path = schedule_path(cross_id, day_type)
        operation = "updated" if os.path.exists(path) else "created"

        if not dry_run:
            _write_schedule(path, schedule)

        return _success(cross_id, day_type, path, operation, dry_run)
    except Exception as error:
        return _error(error, dry_run=dry_run)


def delete_schedule(cross_id, day_type="workday", dry_run=False):
    try:
        cross_id = _normalize_cross_id(cross_id)
        day_type = _normalize_day_type(day_type)
        path = schedule_path(cross_id, day_type)
        existed = os.path.exists(path)

        if existed and not dry_run:
            os.remove(path)

        return {
            "status": "validated" if dry_run else "success",
            "saved": not dry_run,
            "deleted": existed,
            "Cross_id": cross_id,
            "day_type": day_type,
            "file": _file_label(path),
        }
    except Exception as error:
        return _error(error, dry_run=dry_run)
