import json
import math
import os
import tempfile
from pathlib import Path


SCHEDULE_DIR = Path(__file__).resolve().parent / "schedule_json"
MANIFEST_PATH = SCHEDULE_DIR / "time_schedule_manifest.json"
WORKDAY_PREFIX = "Time_schedule_"
WEEKEND_PREFIX = "Time_schedule_weekend_"


def _validate_hourly_schedule(schedule, label):
    if not isinstance(schedule, dict) or not schedule:
        raise ValueError(f"{label} must be a non-empty object")

    normalized = {}
    for raw_hour, raw_values in schedule.items():
        hour = str(raw_hour)
        if not hour.isdigit() or not 0 <= int(hour) <= 23:
            raise ValueError(f"{label} contains invalid hour: {hour}")
        if not isinstance(raw_values, list) or len(raw_values) != 10:
            raise ValueError(f"{label} hour {hour} must contain exactly 10 values")

        values = []
        for index, value in enumerate(raw_values):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    f"{label} hour {hour} value {index} must be a non-negative number"
                )
            values.append(value)
        normalized[hour] = values

    return dict(sorted(normalized.items(), key=lambda item: int(item[0])))


def validate_time_schedule_config(data, expected_cross_id=None):
    if not isinstance(data, dict):
        raise ValueError("time schedule config must be an object")
    if data.get("schema_version") != 1:
        raise ValueError("time schedule schema_version must be 1")

    cross_id = str(data.get("cross_id", ""))
    if not cross_id.isdigit():
        raise ValueError("time schedule cross_id must contain only digits")
    if expected_cross_id is not None and cross_id != str(expected_cross_id):
        raise ValueError(
            f"time schedule cross_id {cross_id} does not match {expected_cross_id}"
        )

    workday = _validate_hourly_schedule(data.get("workday"), "workday")
    raw_weekend = data.get("weekend")
    weekend = (
        None
        if raw_weekend is None
        else _validate_hourly_schedule(raw_weekend, "weekend")
    )

    return {
        "schema_version": 1,
        "cross_id": cross_id,
        "workday": workday,
        "weekend": weekend,
    }


def validate_time_schedule_manifest(data):
    if not isinstance(data, dict):
        raise ValueError("time schedule manifest must be an object")
    if data.get("schema_version") != 1:
        raise ValueError("time schedule manifest schema_version must be 1")

    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("time schedule manifest version must be a positive integer")

    raw_items = data.get("items")
    if not isinstance(raw_items, dict) or not raw_items:
        raise ValueError("time schedule manifest items must be a non-empty object")

    items = {}
    for raw_cross_id, raw_item in raw_items.items():
        cross_id = str(raw_cross_id)
        if not cross_id.isdigit() or not isinstance(raw_item, dict):
            raise ValueError(f"invalid manifest item: {cross_id}")

        expected_data_id = f"time_schedule_{cross_id}.json"
        data_id = raw_item.get("data_id")
        item_version = raw_item.get("version")
        if data_id != expected_data_id:
            raise ValueError(
                f"manifest data_id for {cross_id} must be {expected_data_id}"
            )
        if (
            isinstance(item_version, bool)
            or not isinstance(item_version, int)
            or item_version < 1
        ):
            raise ValueError(
                f"manifest version for {cross_id} must be a positive integer"
            )
        items[cross_id] = {
            "data_id": data_id,
            "version": item_version,
        }

    return {
        "schema_version": 1,
        "version": version,
        "items": dict(sorted(items.items())),
    }


def _read_json(path):
    with open(path, "r", encoding="utf-8-sig") as file:
        return json.load(file)


def _write_json_atomic(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if _read_json(path) == data:
                return False
        except (OSError, json.JSONDecodeError):
            pass

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            json.dump(data, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
    return True


def build_time_schedule_configs(schedule_dir=SCHEDULE_DIR):
    schedule_dir = Path(schedule_dir)
    configs = {}
    for workday_path in sorted(schedule_dir.glob("Time_schedule_*.json")):
        if workday_path.name.startswith(WEEKEND_PREFIX):
            continue

        cross_id = workday_path.stem.removeprefix(WORKDAY_PREFIX)
        if not cross_id.isdigit():
            continue
        weekend_path = schedule_dir / f"{WEEKEND_PREFIX}{cross_id}.json"
        payload = {
            "schema_version": 1,
            "cross_id": cross_id,
            "workday": _read_json(workday_path),
            "weekend": _read_json(weekend_path) if weekend_path.exists() else None,
        }
        normalized = validate_time_schedule_config(
            payload,
            expected_cross_id=cross_id,
        )
        configs[f"time_schedule_{cross_id}.json"] = normalized
    return configs


def build_time_schedule_manifest(configs, version=1):
    items = {}
    for data_id in sorted(configs):
        cross_id = data_id.removeprefix("time_schedule_").removesuffix(".json")
        items[cross_id] = {"data_id": data_id, "version": 1}
    return validate_time_schedule_manifest({
        "schema_version": 1,
        "version": version,
        "items": items,
    })


def apply_time_schedule_config(data, schedule_dir=SCHEDULE_DIR):
    normalized = validate_time_schedule_config(data)
    schedule_dir = Path(schedule_dir)
    cross_id = normalized["cross_id"]
    _write_json_atomic(
        normalized["workday"],
        schedule_dir / f"{WORKDAY_PREFIX}{cross_id}.json",
    )
    if normalized["weekend"] is not None:
        _write_json_atomic(
            normalized["weekend"],
            schedule_dir / f"{WEEKEND_PREFIX}{cross_id}.json",
        )
    return normalized


def save_time_schedule_manifest(data, path=MANIFEST_PATH):
    normalized = validate_time_schedule_manifest(data)
    _write_json_atomic(normalized, path)
    return normalized
