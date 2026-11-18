"""Pilot switch and audit for the runtime flow-to-time allocator.

The DQN caller computes the legacy schedule first. This module can keep that
schedule, shadow the new allocator, or select the new result for explicitly
configured pilot roads. Every error falls back to the legacy schedule.
"""

from lib.road_groups import TONGZHOU_19, road_group
from lib.intersection_strategy import (
    PLATFORM_PHASE_ROAD_IDS, supports_online_experience_growth, uses_platform_phase_timing,
)

from datetime import datetime
import json
import hashlib
from infra.logging import decision_batch_id
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
    "1300086",
    "1300364",
    "1300253",
    "1300179",
    "1300089",
    "1300094",
    "1300230",
    "1300255",
    "1300039",
    "1300108",
    "1300358",
    "1300067",
    "1300120",
    "1300239",
    "1300229",
    "1300153",
    "1300166",
    "1300306",
    "1300409",
    "1300362",
    "1300087",
    "1300147",
    "1700448",
    "1700449",
    "1700450",
    "1700542",
    "1700545",
    "2272",
    "2620",
    '1700062',
    '1700151',
    '1700240',
    '1700311',
    '1700312',
    '1700314',
    '1700345',
    '1700347',
    '1700348',
    '1700451',
    '1700452',
    '1700453',
    '1700454',
    '1700455',
    '1700456',
    '1700544',
    '1700546',
    '1700548',
    '1700549',
    '1700553',
    '1700555',
    '1700556',
    '2703310',
    '2703317',
    '2703318',
    '2703320',
    '2703802',
    '2704740',
    '2704746',
    '2706537',
    '2706540',
    '2707788',
    '2709471',
    '2710273',
    '1700035',
    '1700267',
    '1700269',
    '1700315',
    '2703314',
    '2703491',
    '2704257',
    '2705189',
    '2705192',
    '2705194',
    '2706110',
    '2706134',
    '2706149',
    '2706150',
    '2706152',
})
DEFAULT_PILOT_MODE = "new"
VALID_PILOT_MODES = frozenset({"legacy", "shadow", "new"})
DIRECTIONS = ("U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = PROJECT_ROOT / "lib"
DEFAULT_CROSS_INFO_PATH = LIB_DIR / "cross_info.json"
from app.paths import EXPERIENCE_POOL_DIR, SHADOW_LOG_DIR
from lib.data_ANS.experience_reader import (
    _JSON_CACHE, _CACHE_LOCK, load_json_cached as _load_json_cached,
    load_experience_table, runtime_experience_path,
)
DEFAULT_EXPERIENCE_PATH = EXPERIENCE_POOL_DIR / "online_experience.json"
DEFAULT_LOG_DIRECTORY = SHADOW_LOG_DIR

_LOG_LOCK = threading.Lock()


def _shadow_enabled():
    value = os.environ.get("AITC_FLOW_ALLOCATOR_SHADOW_ENABLED", "1")
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _configured_road_ids():
    configured = os.environ.get("AITC_FLOW_ALLOCATOR_PILOT_ROADS", "").strip()
    if not configured:
        configured = os.environ.get(
            "AITC_FLOW_ALLOCATOR_SHADOW_ROADS",
            "",
        ).strip()
    if not configured:
        return None
    return frozenset(
        item.strip()
        for item in configured.split(",")
        if item.strip()
    )


def _target_road_ids():
    configured = _configured_road_ids()
    if configured is not None:
        return configured
    return DEFAULT_TARGET_ROAD_IDS | PLATFORM_PHASE_ROAD_IDS | TONGZHOU_19


def _pilot_mode(road_id=None):
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
    # 新接入的19组先记录对照，原有已接线路口继续使用其默认模式。
    if (mode == "new" and road_id in TONGZHOU_19
            and road_id not in DEFAULT_TARGET_ROAD_IDS and not uses_platform_phase_timing(road_id)):
        return "shadow"
    return mode


def _configured_path(environment_name, default_path):
    return Path(os.environ.get(environment_name, default_path)).resolve()


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
            "active": bool(decision.get("active", False)),
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
        decisions[direction]["experience_point_count"] = int(
            decision.get("experience_point_count", 0)
        )
        decisions[direction]["threshold_at_selected_time"] = float(
            decision.get("threshold_at_selected_time", 0)
        )
        if "experience_profile" in decision:
            decisions[direction]["experience_profile"] = decision["experience_profile"]
        if "selected_capacity_lane_vector" in decision:
            decisions[direction]["selected_capacity_lane_vector"] = decision["selected_capacity_lane_vector"]
        decisions[direction]["excluded_non_capacity_lanes"] = decision.get("excluded_non_capacity_lanes", {})
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
    # 依据在线配时策略校验输入，新登记路口与已上线批次使用同一门槛。
    if supports_online_experience_growth(record["road_id"]):
        if not record["quality_passed"]:
            return record.get("stage_feedback_issue") or "runtime_input_quality_not_passed"
        if not any(record["flow_input"]["base_direction_vehicle_counts"].values()):
            return "runtime_flow_data_empty"
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
    road_info=None,
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
        "road_group": road_group(road_id),
        "old_schedule": old_vector,
        "runtime_mode": str(runtime_mode),
    }

    try:
        if experience_table is None:
            experience_path = runtime_experience_path(DEFAULT_EXPERIENCE_PATH)
            experience_table = load_experience_table(
                online_path=experience_path, road_id=road_id,
            )
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
            road_info=road_info,
            zero_demand_fallback=uses_platform_phase_timing(road_id),
        )
        new_vector = _schedule_vector(result["time_vector"])
        decisions = _decision_summary(result)
        runtime = result.get("runtime_input", {})
        if "stage_feedback_issue" in runtime:
            record["stage_feedback_issue"] = runtime["stage_feedback_issue"]
        if road_group(road_id) in {"19", "49"}:
            road_table = experience_table.get(road_id, {})
            config = cross_info[road_id]
            record["batch_id"] = decision_batch_id.get()
            record["runtime_input"] = runtime
            record["flow_10min_lane_vectors"] = result["flow_10min"]
            record["effective_cross_info"] = {
                key: config[key] for key in ("phase", "LaneNo", "jtll_ddbh", "Cycle", "zhouqi")
                if key in config
            }
            record["experience_road_sha256"] = hashlib.sha256(json.dumps(
                road_table, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            record["raw_experience_point_counts"] = {
                direction: len(points) for direction, points in road_table.items()
                if isinstance(points, dict)
            }
        record.update({
            "status": "ok",
            "new_schedule": new_vector,
            "difference": [
                new - old
                for old, new in zip(old_vector, new_vector)
            ],
            "cold_start": runtime.get("cold_start", {}),
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
            "extend_stage_validation": {
                key: int(runtime.get("extend", {}).get(key, 0))
                for key in ("invalid_stage_records", "unconfigured_stage_records",
                            "out_of_window_invalid_stage_seconds")
            },
            # 原始方向计数与受控需求分开记录，零需求不能直接解释为没有来车。
            "flow_input": {
                "selected_timestamp_records": int(runtime.get("flow_selection", {}).get("selected_records", 0)),
                "base_direction_vehicle_counts": {
                    direction: sum(runtime.get("observed_flow", {}).get(direction, []))
                    for direction in ("U", "D", "L", "R")
                },
            },
            "extend_timebase": runtime.get("extend", {}).get("timebase", {}),
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
    if record.get("status") == "ok" and (
        runtime_mode == "new" or (runtime_mode == "shadow" and supports_online_experience_growth(road_id))
    ):
        rejection_reason = _new_schedule_rejection_reason(record, old_vector)
        if runtime_mode == "shadow" and rejection_reason:
            record["candidate_rejection_reason"] = rejection_reason
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

    mode = _pilot_mode(road_id)
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
