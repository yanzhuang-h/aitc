"""Pilot switch and audit for the runtime flow-to-time allocator.

The DQN caller computes the legacy schedule first. This module can keep that
schedule, shadow the new allocator, or select the new result for explicitly
configured pilot roads. Every error falls back to the legacy schedule.
"""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import threading
import time

try:
    from lib.data_ANS.flow_time_allocator import allocate_from_runtime_data
except ModuleNotFoundError:  # Supports direct execution from this directory.
    from flow_time_allocator import allocate_from_runtime_data


LOGGER = logging.getLogger("FlowAllocatorShadow")
DEFAULT_TARGET_ROAD_IDS = frozenset({
    "1300069",
    "1300068",
    "1300070",
    "1700125",
})
DEFAULT_PILOT_MODE = "new"
VALID_PILOT_MODES = frozenset({"legacy", "shadow", "new"})
DIRECTIONS = ("U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = PROJECT_ROOT / "lib"
DEFAULT_EXPERIENCE_PATH = LIB_DIR / "experience_pool" / "new_wwx.json"
DEFAULT_CROSS_INFO_PATH = LIB_DIR / "cross_info.json"
DEFAULT_LOG_DIRECTORY = PROJECT_ROOT / "logs_data" / "shadow"

_JSON_CACHE = {}
_CACHE_LOCK = threading.Lock()
_LOG_LOCK = threading.Lock()


def _shadow_enabled():
    value = os.environ.get("AITC_FLOW_ALLOCATOR_SHADOW_ENABLED", "1")
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _target_road_ids():
    configured = os.environ.get("AITC_FLOW_ALLOCATOR_PILOT_ROADS", "").strip()
    if not configured:
        configured = os.environ.get(
            "AITC_FLOW_ALLOCATOR_SHADOW_ROADS",
            "",
        ).strip()
    if not configured:
        return DEFAULT_TARGET_ROAD_IDS
    return frozenset(
        item.strip()
        for item in configured.split(",")
        if item.strip()
    )


def _pilot_mode():
    mode = os.environ.get(
        "AITC_FLOW_ALLOCATOR_PILOT_MODE",
        DEFAULT_PILOT_MODE,
    ).strip().lower()
    if mode not in VALID_PILOT_MODES:
        LOGGER.error(
            "invalid AITC_FLOW_ALLOCATOR_PILOT_MODE=%r; using legacy",
            mode,
        )
        return "legacy"
    return mode


def _configured_path(environment_name, default_path):
    return Path(os.environ.get(environment_name, default_path)).resolve()


def _load_json_cached(path):
    path = Path(path).resolve()
    stat = path.stat()
    version = (stat.st_mtime_ns, stat.st_size)
    with _CACHE_LOCK:
        cached = _JSON_CACHE.get(path)
        if cached and cached["version"] == version:
            return cached["data"]
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise TypeError(f"shadow JSON root must be a dictionary: {path}")
        _JSON_CACHE[path] = {"version": version, "data": data}
        return data


def _schedule_vector(schedule):
    if not isinstance(schedule, (list, tuple)):
        return []
    result = []
    for value in schedule:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            result.append(value)
    return result


def _decision_summary(result):
    decisions = {}
    for direction in DIRECTIONS:
        decision = result.get("decisions", {}).get(direction, {})
        decisions[direction] = {
            "requested_flow": int(decision.get("requested_flow", 0)),
            "selected_green_time": int(
                decision.get("selected_green_time", 0)
            ),
            "table_green_time": int(decision.get("table_green_time", 0)),
            "capacity_at_selected_time": int(
                decision.get("capacity_at_selected_time", 0)
            ),
            "status": decision.get("status", "unknown"),
            "lane_indexes": list(decision.get("lane_indexes", [])),
        }
        if "fallback_source" in decision:
            decisions[direction]["fallback_source"] = decision[
                "fallback_source"
            ]
    return decisions


def _new_schedule_rejection_reason(record, old_vector):
    new_vector = _schedule_vector(record.get("new_schedule"))
    if len(new_vector) != 10:
        return "invalid_new_schedule_length"
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in new_vector
    ):
        return "invalid_new_schedule_value"
    if record.get("positive_flow_zero_directions"):
        return "positive_flow_direction_has_zero_time"
    if any(value > 0 for value in old_vector[:8]) and not any(
        value > 0 for value in new_vector[:8]
    ):
        return "new_schedule_all_directions_zero"
    return None


def _append_jsonl(record, log_directory, observed_at):
    log_directory = Path(log_directory)
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / (
        f"flow_time_allocator_{observed_at:%Y-%m-%d}.jsonl"
    )
    text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with _LOG_LOCK:
        with open(log_path, "a", encoding="utf-8") as file:
            file.write(text)
            file.write("\n")
            file.flush()
    return log_path


def record_shadow_comparison(
    road_id,
    old_schedule,
    flow_map_single_intersection,
    extend_map_single_intersection,
    *,
    experience_table=None,
    cross_info=None,
    log_directory=None,
    observed_at=None,
    runtime_mode="shadow",
):
    """Evaluate and record one shadow result without ever raising to DQN."""
    road_id = str(road_id)
    if not _shadow_enabled() or road_id not in _target_road_ids():
        return None

    observed_at = observed_at or datetime.now().astimezone()
    old_vector = _schedule_vector(old_schedule)
    started_at = time.perf_counter()
    record = {
        "schema_version": 1,
        "observed_at": observed_at.isoformat(timespec="seconds"),
        "road_id": road_id,
        "old_schedule": old_vector,
        "runtime_mode": str(runtime_mode),
    }

    try:
        if experience_table is None:
            experience_path = _configured_path(
                "AITC_FLOW_ALLOCATOR_SHADOW_TABLE",
                DEFAULT_EXPERIENCE_PATH,
            )
            experience_table = _load_json_cached(experience_path)
            record["experience_table"] = str(experience_path)
        else:
            record["experience_table"] = "injected"

        if cross_info is None:
            cross_info_path = _configured_path(
                "AITC_FLOW_ALLOCATOR_SHADOW_CROSS_INFO",
                DEFAULT_CROSS_INFO_PATH,
            )
            cross_info = _load_json_cached(cross_info_path)
            record["cross_info"] = str(cross_info_path)
        else:
            record["cross_info"] = "injected"

        result = allocate_from_runtime_data(
            road_id,
            flow_map_single_intersection,
            extend_map_single_intersection,
            experience_table=experience_table,
            cross_info=cross_info,
        )
        new_vector = _schedule_vector(result["time_vector"])
        decisions = _decision_summary(result)
        runtime = result.get("runtime_input", {})
        record.update({
            "status": "ok",
            "new_schedule": new_vector,
            "difference": [
                new - old
                for old, new in zip(old_vector, new_vector)
            ],
            "quality_passed": bool(runtime.get("quality_passed")),
            "normalization_mode": runtime.get("normalization_mode"),
            "normalization_factor": runtime.get("normalization_factor"),
            "flow_directions": list(runtime.get("flow_directions", [])),
            "extend_directions": list(runtime.get("extend_directions", [])),
            "extend_span_seconds": int(
                runtime.get("extend", {}).get("span_seconds", 0)
            ),
            "extend_coverage_ratio": float(
                runtime.get("extend", {}).get("coverage_ratio", 0.0)
            ),
            "cycle_status": runtime.get("cycle", {}).get("status"),
            "decisions": decisions,
            "positive_flow_zero_directions": [
                direction
                for direction, decision in decisions.items()
                if decision["requested_flow"] > 0
                and decision["selected_green_time"] <= 0
            ],
            "fallback_directions": [
                direction
                for direction, decision in decisions.items()
                if str(decision["status"]).startswith("fallback_")
            ],
        })
    except Exception as error:
        record.update({
            "status": "error",
            "error_type": type(error).__name__,
            "error": str(error),
        })
        LOGGER.exception(
            "flow allocator shadow evaluation failed for road %s",
            road_id,
        )

    rejection_reason = None
    if runtime_mode == "new" and record.get("status") == "ok":
        rejection_reason = _new_schedule_rejection_reason(record, old_vector)
    if runtime_mode == "new" and not rejection_reason and record.get("status") == "ok":
        record["selected_schedule"] = list(record["new_schedule"])
        record["selected_schedule_source"] = "new"
    else:
        record["selected_schedule"] = list(old_vector)
        record["selected_schedule_source"] = "legacy"
        if runtime_mode == "new":
            record["selection_fallback_reason"] = (
                rejection_reason or "new_evaluation_error"
            )

    record["elapsed_ms"] = round(
        (time.perf_counter() - started_at) * 1000,
        3,
    )
    try:
        if log_directory is None:
            log_directory = _configured_path(
                "AITC_FLOW_ALLOCATOR_SHADOW_LOG_DIR",
                DEFAULT_LOG_DIRECTORY,
            )
        log_path = _append_jsonl(record, log_directory, observed_at)
        record["log_path"] = str(log_path)
    except Exception:
        LOGGER.exception(
            "flow allocator shadow log write failed for road %s",
            road_id,
        )
    return record


def select_pilot_schedule(
    road_id,
    legacy_schedule,
    flow_map_single_intersection,
    extend_map_single_intersection,
):
    """Select legacy/shadow/new output for one explicitly wired DQN road.

    ``legacy`` performs no new-module work. ``shadow`` records the comparison
    but returns the legacy schedule. ``new`` returns the new schedule only when
    evaluation succeeds; any disabled/error condition returns the legacy one.
    """
    legacy_vector = _schedule_vector(legacy_schedule)
    road_id = str(road_id)
    if road_id not in _target_road_ids():
        return legacy_vector

    mode = _pilot_mode()
    if mode == "legacy":
        return legacy_vector

    record = record_shadow_comparison(
        road_id,
        legacy_vector,
        flow_map_single_intersection,
        extend_map_single_intersection,
        runtime_mode=mode,
    )
    if not isinstance(record, dict):
        return legacy_vector
    return _schedule_vector(record.get("selected_schedule", legacy_vector))
