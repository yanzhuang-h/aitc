"""Callable fixed-timetable control without importing the Flask service."""

import json
from datetime import datetime
from pathlib import Path

from chinese_calendar import is_workday

from .dqn_control import validate_control_plan
from .types import ControlResult


DEFAULT_SCHEDULE_DIR = Path(__file__).resolve().parents[2] / "time_schedule" / "schedule_json"


def load_intersection_timetable(cross_id, target_time=None, *,
                                schedule_dir=None, runtime_schedules=None):
    """Load the complete 24-hour timetable for one intersection.

    Args:
        cross_id: Intersection ID accepted as string or integer.
        target_time: Local :class:`datetime` or Unix timestamp in seconds used
            to select workday/weekend data. ``None`` means local current time.
        schedule_dir: Optional directory containing `Time_schedule_*.json` and
            `Time_schedule_weekend_*.json`. The project directory is the default.
        runtime_schedules: Optional current outer schedule mapping from the
            time_schedule service. When it contains this intersection, that
            in-memory value takes priority over the local file.

    Returns:
        tuple[dict, str]: The 24-hour mapping and source description. Hour keys
        are strings ``"0"`` through ``"23"`` and values are ten-element plans.

    Raises:
        ValueError: If the intersection ID, timestamp, JSON structure, hour keys,
            or any ten-element control plan is invalid.
        FileNotFoundError: If the selected workday/weekend file does not exist.
    """
    cross_id = str(cross_id).strip()
    if not cross_id:
        raise ValueError("cross_id cannot be empty")
    target_datetime = _as_local_datetime(target_time)

    if runtime_schedules is not None and cross_id in runtime_schedules:
        timetable = runtime_schedules[cross_id]
        source = "time_schedule_runtime"
    else:
        prefix = "Time_schedule_" if is_workday(target_datetime.date()) else "Time_schedule_weekend_"
        timetable_path = Path(schedule_dir or DEFAULT_SCHEDULE_DIR) / f"{prefix}{cross_id}.json"
        with timetable_path.open("r", encoding="utf-8") as schedule_file:
            timetable = json.load(schedule_file)
        source = "time_schedule_workday" if prefix == "Time_schedule_" else "time_schedule_weekend"

    return _validate_timetable(timetable), source


def get_timetable_plan(cross_id, target_time=None, *, schedule_dir=None,
                       runtime_schedules=None):
    """Return the fixed control plan for an intersection and local hour.

    This is the anomaly-path counterpart to ``generate_intersection_plan``.
    Inputs select an intersection and time; output uses the same ``ControlResult``
    schema as the DQN function. Missing/invalid schedules return ``success=false``
    with an all-zero plan and an explanatory error, without raising to the caller.
    """
    normalized_cross_id = str(cross_id).strip()
    try:
        target_datetime = _as_local_datetime(target_time)
        timetable, source = load_intersection_timetable(
            normalized_cross_id,
            target_datetime,
            schedule_dir=schedule_dir,
            runtime_schedules=runtime_schedules,
        )
        plan, warnings = validate_control_plan(timetable[str(target_datetime.hour)])
        return ControlResult(
            success=True,
            cross_id=normalized_cross_id,
            plan=plan,
            source=source,
            warnings=warnings,
            model_info={"schedule_hour": target_datetime.hour},
        )
    except Exception as exc:
        return ControlResult(
            success=False,
            cross_id=normalized_cross_id,
            plan=[0] * 10,
            source="time_schedule",
            error=f"{type(exc).__name__}: {exc}",
        )


def _as_local_datetime(value):
    if value is None:
        return datetime.now()
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    raise ValueError("target_time must be a datetime, Unix seconds, or None")


def _validate_timetable(timetable):
    if not isinstance(timetable, dict):
        raise ValueError("timetable must be an object keyed by hour")
    normalized = {}
    for hour in range(24):
        hour_key = str(hour)
        if hour_key not in timetable:
            raise ValueError(f"timetable is missing hour {hour_key}")
        normalized[hour_key], _ = validate_control_plan(timetable[hour_key])
    return normalized

