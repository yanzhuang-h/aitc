import argparse
import copy
import json
import os
import sys
import tempfile
import threading
import time
from datetime import date

from chinese_calendar import is_workday


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FLOATING_VALUE_PATH = os.path.join(BASE_DIR, "floating_value.json")

TIME_SLOT_MINUTES = 10
PHASE_COUNT = 9
DAY_KEYS = {"yes", "no"}
PHASE_OFFSET_KEYS = ("phase_\u504f\u79fb", "phase_offset", "phase_offsets")

_cache_mtime = None
_cache_data = []
_write_lock = threading.Lock()


def _load_floating_value(path=FLOATING_VALUE_PATH):
    global _cache_mtime, _cache_data

    if not os.path.exists(path):
        _cache_mtime = None
        _cache_data = []
        return _cache_data

    mtime = os.path.getmtime(path)
    if _cache_mtime == mtime:
        return _cache_data

    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    if data == {}:
        data = []
    elif isinstance(data, dict):
        data = [data]
    elif not isinstance(data, list):
        data = []

    _cache_mtime = mtime
    _cache_data = data
    return _cache_data


def _read_floating_value_uncached(path=FLOATING_VALUE_PATH):
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    if data == {}:
        return []
    if isinstance(data, dict):
        return [data]
    if not isinstance(data, list):
        raise ValueError("floating value file must contain a JSON object or array")

    return data


def _save_floating_value(data, path=FLOATING_VALUE_PATH):
    global _cache_mtime, _cache_data

    target_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(target_dir, exist_ok=True)

    temp_path = None
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
    _cache_data = []


def replace_floating_value_records(data, path=FLOATING_VALUE_PATH, check_rules=True):
    """Validate and atomically replace all floating-value records."""
    if data == {}:
        data = []
    elif isinstance(data, dict):
        data = [data]

    _validate_stored_records(data, check_rules=check_rules)
    with _write_lock:
        _save_floating_value(data, path)


def _get_phase_rule_config():
    project_root = os.path.dirname(BASE_DIR)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        from phase_check import get_intersection_result_config

        return get_intersection_result_config(), None
    except Exception as error:
        return {}, str(error)


def _normalize_key(value):
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def _require_payload_value(payload, key):
    if key not in payload:
        raise ValueError(f"missing required payload field: {key}")
    return payload[key]


def _normalize_day_key(value):
    day_key = str(value).strip().lower()
    if day_key not in DAY_KEYS:
        raise ValueError("IS_work_day must be 'yes' or 'no'")
    return day_key


def _normalize_time_slot_value(value):
    raw_value = str(value).strip()
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

    if minute % TIME_SLOT_MINUTES != 0:
        raise ValueError(
            f"time minute must align to {TIME_SLOT_MINUTES}-minute slots: {raw_value}"
        )

    return f"{hour:02d}:{minute:02d}"


def _slot_to_minutes(slot):
    hour, minute = slot.split(":")
    return int(hour) * 60 + int(minute)


def _build_time_slot_range(start_slot, end_slot):
    start_minutes = _slot_to_minutes(start_slot)
    end_minutes = _slot_to_minutes(end_slot)

    if end_minutes < start_minutes:
        raise ValueError("time_during_end must be greater than or equal to time_during_start")

    slots = []
    for slot_minutes in range(start_minutes, end_minutes + 1, TIME_SLOT_MINUTES):
        hour = slot_minutes // 60
        minute = slot_minutes % 60
        slots.append(f"{hour:02d}:{minute:02d}")
    return slots


def _payload_phase_offsets(payload):
    for key in PHASE_OFFSET_KEYS:
        if key in payload:
            return payload[key]
    raise ValueError(
        "missing required payload field: phase_\u504f\u79fb"
    )


def _normalize_phase_offsets(offsets):
    if not isinstance(offsets, (list, tuple)):
        raise ValueError("phase offsets must be a list")

    if len(offsets) > PHASE_COUNT:
        raise ValueError(f"phase offsets must contain no more than {PHASE_COUNT} values")

    normalized = []
    for index, offset in enumerate(offsets):
        try:
            normalized.append(int(offset))
        except (TypeError, ValueError):
            raise ValueError(f"phase offset at index {index} must be an integer")

    normalized.extend([0] * (PHASE_COUNT - len(normalized)))
    return normalized


def _normalize_floating_update_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    cross_id = _normalize_key(_require_payload_value(payload, "Cross_id"))
    change_id = _normalize_key(_require_payload_value(payload, "Change_id"))
    day_key = _normalize_day_key(_require_payload_value(payload, "IS_work_day"))
    start_slot = _normalize_time_slot_value(
        _require_payload_value(payload, "time_during_start")
    )
    end_slot = _normalize_time_slot_value(
        _require_payload_value(payload, "time_during_end")
    )
    slots = _build_time_slot_range(start_slot, end_slot)
    offsets = _normalize_phase_offsets(_payload_phase_offsets(payload))

    return {
        "cross_id": cross_id,
        "change_id": change_id,
        "day_key": day_key,
        "start_slot": start_slot,
        "end_slot": end_slot,
        "slots": slots,
        "offsets": offsets,
    }


def _ensure_floating_update_target(data, normalized, allow_create_intersection=False):
    day_key = normalized["day_key"]
    cross_id = normalized["cross_id"]

    if day_key not in data:
        data[day_key] = {}
    if not isinstance(data[day_key], dict):
        raise ValueError(f"floating value day section must be an object: {day_key}")

    if cross_id not in data[day_key] and not allow_create_intersection:
        raise ValueError(
            f"Cross_id {cross_id} does not exist in floating value day section {day_key}"
        )

    data[day_key].setdefault(cross_id, {})
    if not isinstance(data[day_key][cross_id], dict):
        raise ValueError(f"floating value Cross_id section must be an object: {cross_id}")

    return data[day_key][cross_id]


def _check_floating_update_rules(normalized):
    issues = []
    phase_rules, import_error = _get_phase_rule_config()

    if import_error:
        issues.append(f"phase rule config is unavailable: {import_error}")
        return {"passed": False, "issues": issues, "plan_rules": None}

    cross_id = normalized["cross_id"]
    change_id = normalized["change_id"]
    offsets = normalized["offsets"]

    intersection_rules = phase_rules.get(cross_id)
    if not intersection_rules:
        issues.append(f"Cross_id {cross_id} does not exist in phase rule config")
        return {"passed": False, "issues": issues, "plan_rules": None}

    plan_rules = intersection_rules.get(change_id)
    if not plan_rules:
        issues.append(f"Change_id {change_id} is not defined for Cross_id {cross_id}")
        return {"passed": False, "issues": issues, "plan_rules": None}

    for phase_index, offset in enumerate(offsets):
        if offset == 0:
            continue

        phase_key = str(phase_index)
        if phase_key not in plan_rules:
            issues.append(
                f"phase index {phase_index} has non-zero offset {offset}, "
                f"but Change_id {change_id} has no rule for this phase"
            )
            continue

        try:
            min_value, max_value = plan_rules[phase_key]
            allowed_width = int(max_value) - int(min_value)
        except (TypeError, ValueError):
            issues.append(
                f"phase index {phase_index} rule is invalid: {plan_rules[phase_key]}"
            )
            continue

        if allowed_width < 0:
            issues.append(
                f"phase index {phase_index} rule max is smaller than min: "
                f"{plan_rules[phase_key]}"
            )
            continue

        if abs(offset) > allowed_width:
            issues.append(
                f"phase index {phase_index} offset {offset} exceeds allowed rule "
                f"width {allowed_width} ({min_value}-{max_value})"
            )

    return {
        "passed": not issues,
        "issues": issues,
        "plan_rules": copy.deepcopy(plan_rules),
    }


def _validate_stored_records(data, check_rules=True):
    """Reject malformed existing records before an update can rewrite the file."""
    if not isinstance(data, list):
        raise ValueError("floating value file must contain an array of records")

    for index, record in enumerate(data):
        try:
            normalized = _normalize_floating_update_payload(record)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid floating value record at index {index}: {error}")

        if check_rules:
            rule_check = _check_floating_update_rules(normalized)
            if not rule_check["passed"]:
                raise ValueError(
                    f"invalid floating value record at index {index}: "
                    f"{'; '.join(rule_check['issues'])}"
                )


def validate_floating_value_update(
    payload,
    path=FLOATING_VALUE_PATH,
    allow_create_intersection=False,
    check_rules=True,
):
    normalized = _normalize_floating_update_payload(payload)
    data = _read_floating_value_uncached(path)
    _validate_stored_records(data, check_rules=check_rules)
    rule_check = (
        _check_floating_update_rules(normalized)
        if check_rules
        else {"passed": True, "issues": [], "plan_rules": None}
    )

    return {
        "status": "valid" if rule_check["passed"] else "invalid",
        "reason": None if rule_check["passed"] else "; ".join(rule_check["issues"]),
        "cross_id": normalized["cross_id"],
        "change_id": normalized["change_id"],
        "is_work_day": normalized["day_key"],
        "time_during_start": normalized["start_slot"],
        "time_during_end": normalized["end_slot"],
        "slots": normalized["slots"],
        "slot_count": len(normalized["slots"]),
        "phase_offsets": normalized["offsets"],
        "rule_check": rule_check,
    }


def update_floating_value(
    payload,
    path=FLOATING_VALUE_PATH,
    dry_run=False,
    allow_create_intersection=False,
    check_rules=True,
):
    normalized = _normalize_floating_update_payload(payload)
    rule_check = (
        _check_floating_update_rules(normalized)
        if check_rules
        else {"passed": True, "issues": [], "plan_rules": None}
    )

    if not rule_check["passed"]:
        return {
            "status": "error",
            "saved": False,
            "dry_run": dry_run,
            "reason": "; ".join(rule_check["issues"]),
            "cross_id": normalized["cross_id"],
            "change_id": normalized["change_id"],
            "is_work_day": normalized["day_key"],
            "time_during_start": normalized["start_slot"],
            "time_during_end": normalized["end_slot"],
            "slot_count": len(normalized["slots"]),
            "phase_offsets": normalized["offsets"],
            "rule_check": rule_check,
        }

    with _write_lock:
        data = _read_floating_value_uncached(path)
        _validate_stored_records(data, check_rules=check_rules)
        record = {
            "Cross_id": normalized["cross_id"],
            "Change_id": normalized["change_id"],
            "IS_work_day": normalized["day_key"],
            "time_during_start": normalized["start_slot"],
            "time_during_end": normalized["end_slot"],
            "phase_\u504f\u79fb": list(normalized["offsets"]),
        }
        identity = (
            normalized["cross_id"],
            normalized["change_id"],
            normalized["day_key"],
            normalized["start_slot"],
            normalized["end_slot"],
        )
        replace_index = None
        before = None
        for index, existing in enumerate(data):
            try:
                existing_normalized = _normalize_floating_update_payload(existing)
            except (TypeError, ValueError):
                continue
            existing_identity = (
                existing_normalized["cross_id"],
                existing_normalized["change_id"],
                existing_normalized["day_key"],
                existing_normalized["start_slot"],
                existing_normalized["end_slot"],
            )
            if existing_identity == identity:
                replace_index = index
                before = copy.deepcopy(existing)

        if replace_index is None:
            data.append(record)
        else:
            data[replace_index] = record

        changes = [{
            "record_index": replace_index if replace_index is not None else len(data) - 1,
            "before": before,
            "after": copy.deepcopy(record),
        }]

        if not dry_run:
            _save_floating_value(data, path)

    return {
        "status": "validated" if dry_run else "success",
        "saved": not dry_run,
        "message": "validation success" if dry_run else "save success",
        "dry_run": dry_run,
        "path": os.path.abspath(path),
        "cross_id": normalized["cross_id"],
        "change_id": normalized["change_id"],
        "is_work_day": normalized["day_key"],
        "time_during_start": normalized["start_slot"],
        "time_during_end": normalized["end_slot"],
        "slot_count": len(normalized["slots"]),
        "phase_offsets": normalized["offsets"],
        "rule_check": rule_check,
        "changes": changes,
    }


def validate_and_save_floating_value(
    payload,
    path=FLOATING_VALUE_PATH,
    dry_run=False,
    allow_create_intersection=False,
    check_rules=True,
):
    try:
        return update_floating_value(
            payload,
            path=path,
            dry_run=dry_run,
            allow_create_intersection=allow_create_intersection,
            check_rules=check_rules,
        )
    except Exception as error:
        return {
            "status": "error",
            "saved": False,
            "dry_run": dry_run,
            "reason": str(error),
        }


def _workday_key(current_time):
    current_date = date.fromtimestamp(current_time)
    return "yes" if is_workday(current_date) else "no"


def _time_slot_key(current_time):
    local_time = time.localtime(current_time)
    minute = (local_time.tm_min // TIME_SLOT_MINUTES) * TIME_SLOT_MINUTES
    return f"{local_time.tm_hour:02d}:{minute:02d}"


def _select_rule(rules, key):
    if not isinstance(rules, dict):
        return None
    return rules.get(key) or rules.get("*") or rules.get("default")


def _apply_phase_offsets(action, offsets):
    if not isinstance(action, list):
        return action

    adjusted = list(action)

    if isinstance(offsets, dict):
        items = offsets.items()
    elif isinstance(offsets, list):
        items = enumerate(offsets)
    else:
        return adjusted

    for phase_index, offset in items:
        try:
            phase_index = int(phase_index)
            offset = int(offset)
        except (TypeError, ValueError):
            continue

        if phase_index < 0 or phase_index >= min(len(adjusted), PHASE_COUNT):
            continue

        if adjusted[phase_index] == 0:
            continue

        adjusted[phase_index] = max(0, int(adjusted[phase_index]) + offset)

    return adjusted


def _build_phase_changes(before_action, after_action):
    if not isinstance(before_action, list) or not isinstance(after_action, list):
        return []

    changes = []
    for phase_index in range(min(len(before_action), len(after_action), PHASE_COUNT)):
        before_value = before_action[phase_index]
        after_value = after_action[phase_index]
        if before_value == after_value:
            continue

        try:
            delta = int(after_value) - int(before_value)
        except (TypeError, ValueError):
            delta = None

        changes.append({
            "phase_index": phase_index,
            "before": before_value,
            "after": after_value,
            "delta": delta,
        })

    return changes


def _empty_report(current_time=None):
    if current_time is None:
        return {
            "workday": None,
            "time_slot": None,
            "modifications": [],
        }

    return {
        "workday": _workday_key(current_time),
        "time_slot": _time_slot_key(current_time),
        "modifications": [],
    }


def apply_floating_value(action_map, current_time=None, path=FLOATING_VALUE_PATH, return_report=False):
    """
    Apply floating offsets after global coordination and before phase_check.

    floating_value.json is an array of time-range records. Each record uses the
    same fields accepted by update_floating_value(). Range boundaries are inclusive.
    When ranges overlap, the last matching record wins.
    """
    if current_time is None:
        current_time = time.time()

    report = _empty_report(current_time)
    floating_data = _load_floating_value(path)
    if not floating_data:
        return (action_map, report) if return_report else action_map

    workday_key = _workday_key(current_time)
    time_slot_key = _time_slot_key(current_time)
    report["workday"] = workday_key
    report["time_slot"] = time_slot_key

    adjusted_map = copy.deepcopy(action_map)

    for intersection_id, action in adjusted_map.items():
        try:
            plan_id = _normalize_key(action[9])
        except (TypeError, IndexError):
            continue

        offsets = None
        for record in floating_data:
            try:
                normalized = _normalize_floating_update_payload(record)
            except (TypeError, ValueError):
                continue
            if normalized["day_key"] != workday_key:
                continue
            if normalized["cross_id"] != _normalize_key(intersection_id):
                continue
            if normalized["change_id"] != plan_id:
                continue
            if time_slot_key not in normalized["slots"]:
                continue
            offsets = normalized["offsets"]

        if offsets is None:
            continue

        before_action = copy.deepcopy(action)
        after_action = _apply_phase_offsets(action, offsets)
        phase_changes = _build_phase_changes(before_action, after_action)
        if not phase_changes:
            continue

        adjusted_map[intersection_id] = after_action
        if return_report:
            report["modifications"].append({
                "intersection_id": intersection_id,
                "plan_id": plan_id,
                "offsets": offsets,
                "before": before_action,
                "after_floating": copy.deepcopy(after_action),
                "phase_changes": phase_changes,
            })

    return (adjusted_map, report) if return_report else adjusted_map


def build_empty_floating_template(intersection_plan_map):
    template = []
    for day_key in ("yes", "no"):
        for intersection_id, plan_ids in intersection_plan_map.items():
            for plan_id in plan_ids:
                template.append({
                    "Cross_id": str(intersection_id),
                    "Change_id": str(plan_id),
                    "IS_work_day": day_key,
                    "time_during_start": "00:00",
                    "time_during_end": "23:50",
                    "phase_\u504f\u79fb": [0] * PHASE_COUNT,
                })

    return template


def _load_update_payload_from_args(args):
    if args.payload_file:
        with open(args.payload_file, "r", encoding="utf-8-sig") as file:
            return json.load(file)

    return json.loads(args.payload)


def _main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate or save updates to floating_value.json."
    )
    payload_source = parser.add_mutually_exclusive_group(required=True)
    payload_source.add_argument(
        "--payload",
        help="JSON payload string.",
    )
    payload_source.add_argument(
        "--payload-file",
        help="Path to a JSON payload file.",
    )
    parser.add_argument(
        "--path",
        default=FLOATING_VALUE_PATH,
        help="Path to floating_value.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and build the update report without saving.",
    )
    parser.add_argument(
        "--allow-create-intersection",
        action="store_true",
        help="Allow creating a missing Cross_id section in floating_value.json.",
    )
    parser.add_argument(
        "--no-rule-check",
        action="store_true",
        help="Skip phase rule checks. This should only be used for diagnostics.",
    )

    args = parser.parse_args(argv)
    try:
        payload = _load_update_payload_from_args(args)
        report = validate_and_save_floating_value(
            payload,
            path=args.path,
            dry_run=args.dry_run,
            allow_create_intersection=args.allow_create_intersection,
            check_rules=not args.no_rule_check,
        )
    except Exception as error:
        report = {
            "status": "error",
            "saved": False,
            "dry_run": args.dry_run,
            "reason": str(error),
        }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
