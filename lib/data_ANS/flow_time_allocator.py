"""Independent runtime flow to green-time allocator.

This module deliberately does not modify or call ``cha1.py``.  It provides a
pure, inspectable table lookup plus a three-argument runtime adapter so the old
behavior can be compared against a lane-policy-aware implementation.
"""

from collections import Counter
import json
import math
from pathlib import Path

try:
    from lib.data_ANS.cycle_quality import (
        MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        compress_stage_layers,
        find_complete_cycles,
        group_consecutive_same_pattern_cycles,
        normalize_cycle_patterns,
        split_cycle_group_on_stage_change,
    )
    from lib.data_ANS.lane_policy import (
        configured_movement_lane_policy,
        policy_metadata,
    )
except ModuleNotFoundError:  # Supports direct execution from this directory.
    from cycle_quality import (
        MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        compress_stage_layers,
        find_complete_cycles,
        group_consecutive_same_pattern_cycles,
        normalize_cycle_patterns,
        split_cycle_group_on_stage_change,
    )
    from lane_policy import configured_movement_lane_policy, policy_metadata


LANE_COUNT = 10
DIRECTIONS = ("U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL")
BASE_DIRECTIONS = ("U", "D", "L", "R")
DEFAULT_SATURATION_RATIO = 0.80
DEFAULT_MAX_GREEN_TIME = 150
DEFAULT_TARGET_FLOW_SECONDS = 600
DEFAULT_FULL_WINDOW_MIN_SECONDS = 570
DEFAULT_MAX_STAGE_GAP_SECONDS = 3
DEFAULT_SAFE_FALLBACK_GREEN_TIME = 30

LIB_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EXPERIENCE_PATH = LIB_DIR / "experience_pool" / "new_wwx.json"
DEFAULT_CROSS_INFO_PATH = LIB_DIR / "cross_info.json"

PHASE_DIRECTION_MAP = {
    "UD": ("U", "D"),
    "DU": ("U", "D"),
    "LR": ("L", "R"),
    "RL": ("R", "L"),
    "UDL": ("UTL", "DTL"),
    "DUL": ("UTL", "DTL"),
    "LRL": ("LTL", "RTL"),
    "U": ("UTL", "U"),
    "D": ("DTL", "D"),
    "L": ("LTL", "L"),
    "R": ("RTL", "R"),
    "LTD": ("LTL", "D"),
    "P": (),
}


def _normalize_vector(vector):
    if not isinstance(vector, (list, tuple)) or not 1 <= len(vector) <= LANE_COUNT:
        raise ValueError(
            f"flow vector must contain between 1 and {LANE_COUNT} lanes"
        )
    result = []
    for value in vector:
        if isinstance(value, bool):
            raise ValueError("flow values must be integers")
        number = int(value)
        if number < 0 or number != value:
            raise ValueError("flow values must be non-negative integers")
        result.append(number)
    return result + [0] * (LANE_COUNT - len(result))


def _add_vector(target, direction, vector):
    if direction not in DIRECTIONS:
        return False
    values = _normalize_vector(vector)
    for index, value in enumerate(values):
        target[direction][index] += value
    return True


def aggregate_10min_flow(flow_input):
    """Normalize direct vectors or the server's timestamp -> ``pass`` map.

    Runtime maps use seven lane slots.  Experience tables use ten, so shorter
    valid vectors are padded on the right without shifting lane indexes.
    """
    if not isinstance(flow_input, dict):
        raise TypeError("10-minute flow input must be a dictionary")

    result = {direction: [0] * LANE_COUNT for direction in DIRECTIONS}
    stats = Counter()
    directions_seen = set()
    direct_vector_seen = False

    for direction in DIRECTIONS:
        if direction in flow_input and isinstance(flow_input[direction], (list, tuple)):
            _add_vector(result, direction, flow_input[direction])
            direct_vector_seen = True
            directions_seen.add(direction)
            stats["direct_direction_vectors"] += 1

    if direct_vector_seen:
        stats["input_mode"] = "direction_vectors"
        stats["directions_seen"] = sorted(directions_seen)
        return result, dict(stats)

    for record in flow_input.values():
        if not isinstance(record, dict):
            stats["ignored_non_mapping_record"] += 1
            continue
        pass_map = record.get("pass")
        if not isinstance(pass_map, dict):
            stats["ignored_record_without_pass"] += 1
            continue
        for direction, vector in pass_map.items():
            if _add_vector(result, str(direction), vector):
                directions_seen.add(str(direction))
                stats["pass_direction_vectors"] += 1
            else:
                stats["ignored_invalid_direction"] += 1
    stats["input_mode"] = "timestamp_pass_map"
    stats["directions_seen"] = sorted(directions_seen)
    return result, dict(stats)


def _active_direction_set(active_directions):
    if active_directions is None:
        return set(DIRECTIONS)
    if isinstance(active_directions, dict):
        return {
            str(direction)
            for direction, enabled in active_directions.items()
            if enabled and str(direction) in DIRECTIONS
        }
    return {
        str(direction)
        for direction in active_directions
        if str(direction) in DIRECTIONS
    }


def _direction_flow(flow_vectors, direction, directions_seen):
    if direction.endswith("TL") and direction not in directions_seen:
        return flow_vectors.get(direction[0], [0] * LANE_COUNT)
    return flow_vectors.get(direction, [0] * LANE_COUNT)


def _table_points(direction_table, min_green_time, max_green_time):
    points = []
    if not isinstance(direction_table, dict):
        return points
    for raw_time, raw_vector in direction_table.items():
        try:
            green_time = int(raw_time)
            vector = _normalize_vector(raw_vector)
        except (TypeError, ValueError):
            continue
        if min_green_time <= green_time <= max_green_time:
            points.append((green_time, vector))
    return sorted(points, key=lambda item: item[0])


def _flow_directions(flow_vectors, cross_config, directions_seen):
    """Return controlled movements with positive demand in the flow window."""
    active = set()
    for direction in DIRECTIONS:
        lane_indexes = configured_movement_lane_policy(
            cross_config,
            direction,
            LANE_COUNT,
        )["eligible"]
        if not lane_indexes:
            continue
        vector = _direction_flow(flow_vectors, direction, directions_seen)
        if sum(vector[index] for index in lane_indexes) > 0:
            active.add(direction)
    return active


def _fallback_green_time(
    road_table,
    direction,
    min_green_time,
    max_green_time,
    safe_fallback_green_time,
):
    """Find a bounded non-zero fallback when a direction has no table points."""
    related_directions = []
    if direction.endswith("TL"):
        related_directions.append(direction[0])
    else:
        related_directions.append(direction + "TL")

    for related in related_directions:
        points = _table_points(
            road_table.get(related, {}),
            min_green_time,
            max_green_time,
        )
        if points:
            return points[-1][0], f"related_direction:{related}"

    all_points = []
    for direction_table in road_table.values():
        all_points.extend(
            _table_points(direction_table, min_green_time, max_green_time)
        )
    if all_points:
        return max(time for time, _ in all_points), "road_max_available_time"

    fallback = max(
        min_green_time,
        min(max_green_time, int(safe_fallback_green_time)),
    )
    return fallback, "safe_fallback_time"


def allocate_green_times(
    road_id,
    flow_10min,
    experience_table,
    cross_info,
    *,
    active_directions=None,
    saturation_ratio=DEFAULT_SATURATION_RATIO,
    left_turn_extra_seconds=0,
    safe_fallback_green_time=DEFAULT_SAFE_FALLBACK_GREEN_TIME,
    min_green_time=1,
    max_green_time=DEFAULT_MAX_GREEN_TIME,
):
    """Allocate one green time per direction from a 10-minute flow vector.

    ``experience_table`` is the road-level table with direction keys.  Capacity
    and demand are summed only over lanes classified as capacity-eligible by
    :mod:`lane_policy`; raw right-turn/unrestricted flow therefore cannot
    increase a controlled movement's requested green time.  Positive controlled
    flow always activates its movement, even when ``active_directions`` is
    incomplete.  Missing table points use a bounded, audited fallback instead
    of silently returning zero.
    """
    saturation_ratio = float(saturation_ratio)
    if not 0 < saturation_ratio <= 1:
        raise ValueError("saturation_ratio must be in the interval (0, 1]")
    min_green_time = int(min_green_time)
    max_green_time = int(max_green_time)
    if min_green_time > max_green_time:
        raise ValueError("min_green_time cannot exceed max_green_time")

    road_id = str(road_id)
    road_config = cross_info.get(road_id, {})
    road_table = experience_table.get(road_id, experience_table)
    if not isinstance(road_table, dict):
        raise TypeError("experience table road data must be a dictionary")

    flow_vectors, input_stats = aggregate_10min_flow(flow_10min)
    directions_seen = set(input_stats.get("directions_seen", []))
    active = _active_direction_set(active_directions)
    # Flow is authoritative for demand.  An imperfect caller-provided active
    # set or a malformed extend window must never zero a controlled movement
    # that has positive demand.
    active.update(_flow_directions(flow_vectors, road_config, directions_seen))
    times = {direction: 0 for direction in DIRECTIONS}
    decisions = {}

    for direction in DIRECTIONS:
        selection = configured_movement_lane_policy(
            road_config,
            direction,
            LANE_COUNT,
        )
        lane_indexes = sorted(selection["eligible"])
        excluded_lanes = {
            str(lane): details["lane_type"]
            for lane, details in sorted(selection["excluded"].items())
        }
        decision = {
            "active": direction in active,
            "lane_indexes": lane_indexes,
            "excluded_non_capacity_lanes": excluded_lanes,
            "requested_flow": 0,
            "selected_green_time": 0,
            "table_green_time": 0,
            "capacity_at_selected_time": 0,
            "threshold_at_selected_time": 0.0,
            "status": "inactive",
        }
        if direction not in active:
            decisions[direction] = decision
            continue
        if not lane_indexes:
            fallback_time = max(
                min_green_time,
                min(max_green_time, int(safe_fallback_green_time)),
            )
            times[direction] = fallback_time
            decision.update({
                "selected_green_time": fallback_time,
                "table_green_time": fallback_time,
                "fallback_source": "safe_fallback_time",
                "status": "fallback_no_controlled_capacity_lanes",
            })
            decisions[direction] = decision
            continue

        vector = _direction_flow(flow_vectors, direction, directions_seen)
        requested_flow = sum(vector[index] for index in lane_indexes)
        decision["requested_flow"] = requested_flow
        points = _table_points(
            road_table.get(direction, {}),
            min_green_time,
            max_green_time,
        )
        if not points:
            fallback_time, fallback_source = _fallback_green_time(
                road_table,
                direction,
                min_green_time,
                max_green_time,
                safe_fallback_green_time,
            )
            extra = int(left_turn_extra_seconds) if direction.endswith("TL") else 0
            selected_time = min(max_green_time, fallback_time + max(0, extra))
            times[direction] = selected_time
            decision.update({
                "selected_green_time": selected_time,
                "table_green_time": fallback_time,
                "left_turn_extra_seconds": extra,
                "fallback_source": fallback_source,
                "status": "fallback_missing_experience_points",
            })
            decisions[direction] = decision
            continue

        chosen_time, chosen_vector = points[-1]
        status = "over_capacity_at_max_time"
        for table_time, table_vector in points:
            capacity = sum(table_vector[index] for index in lane_indexes)
            threshold = capacity * saturation_ratio
            if threshold >= requested_flow:
                chosen_time = table_time
                chosen_vector = table_vector
                status = (
                    "zero_demand_minimum_time"
                    if requested_flow == 0
                    else "matched_capacity_threshold"
                )
                break

        capacity = sum(chosen_vector[index] for index in lane_indexes)
        threshold = capacity * saturation_ratio
        extra = int(left_turn_extra_seconds) if direction.endswith("TL") else 0
        selected_time = min(max_green_time, chosen_time + max(0, extra))
        times[direction] = selected_time
        decision.update({
            "selected_green_time": selected_time,
            "table_green_time": chosen_time,
            "capacity_at_selected_time": capacity,
            "threshold_at_selected_time": round(threshold, 3),
            "left_turn_extra_seconds": extra,
            "status": status,
        })
        decisions[direction] = decision

    return {
        "road_id": road_id,
        "times": times,
        "direction_time_vector": [times[direction] for direction in DIRECTIONS],
        # cha1.py historically returns 10 positions; keep two reserved zeros
        # so callers can compare without reshaping the result.
        "time_vector": [times[direction] for direction in DIRECTIONS] + [0, 0],
        "flow_10min": flow_vectors,
        "active_directions": sorted(active),
        "saturation_ratio": saturation_ratio,
        "safe_fallback_green_time": int(safe_fallback_green_time),
        "input_stats": input_stats,
        "lane_policy": policy_metadata(),
        "decisions": decisions,
    }


def _load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _timestamp_seconds(value):
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp) or timestamp <= 0:
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return int(timestamp)


def _normalized_stage(value):
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return None


def normalize_runtime_extend(
    road_id,
    extend_map_single_intersection,
    *,
    max_stage_gap_seconds=DEFAULT_MAX_STAGE_GAP_SECONDS,
):
    """Convert Server ``extend`` records to one cleaned stage per second."""
    if not isinstance(extend_map_single_intersection, dict):
        raise TypeError("runtime extend input must be a dictionary")

    road_id = str(road_id)
    stage_candidates = {}
    stats = Counter()
    for raw_timestamp, raw_payload in extend_map_single_intersection.items():
        timestamp = _timestamp_seconds(raw_timestamp)
        if timestamp is None:
            stats["invalid_timestamp_records"] += 1
            continue
        payloads = raw_payload if isinstance(raw_payload, list) else [raw_payload]
        for payload in payloads:
            if not isinstance(payload, dict):
                stats["invalid_payload_records"] += 1
                continue
            payload_road_id = payload.get("CrossId")
            if payload_road_id is not None and str(payload_road_id) != road_id:
                stats["cross_id_mismatch_records"] += 1
                continue
            stage = _normalized_stage(payload.get("curStageNo"))
            if stage is None:
                stats["invalid_stage_records"] += 1
                continue
            stage_candidates.setdefault(timestamp, set()).add(stage)
            stats["accepted_payload_records"] += 1

    if not stage_candidates:
        return {}, {
            **dict(stats),
            "start": None,
            "end": None,
            "span_seconds": 0,
            "observed_seconds": 0,
            "valid_seconds": 0,
            "coverage_ratio": 0.0,
        }

    observed = {}
    conflict_seconds = set()
    for timestamp, candidates in stage_candidates.items():
        if len(candidates) == 1:
            observed[timestamp] = next(iter(candidates))
        else:
            observed[timestamp] = "-1"
            conflict_seconds.add(timestamp)

    start = min(observed)
    end = max(observed)
    cleaned = {}
    last_observed_timestamp = None
    last_valid_stage = None
    for timestamp in range(start, end + 1):
        if timestamp in observed:
            stage = observed[timestamp]
            last_observed_timestamp = timestamp
            if timestamp in conflict_seconds:
                cleaned[timestamp] = "-1"
                stats["conflicting_seconds"] += 1
            elif stage == "-1":
                if last_valid_stage is None:
                    cleaned[timestamp] = "-1"
                    stats["unresolved_minus_one_seconds"] += 1
                else:
                    cleaned[timestamp] = last_valid_stage
                    stats["inherited_minus_one_seconds"] += 1
            else:
                cleaned[timestamp] = stage
                last_valid_stage = stage
            continue

        distance = (
            timestamp - last_observed_timestamp
            if last_observed_timestamp is not None
            else int(max_stage_gap_seconds) + 1
        )
        if distance <= int(max_stage_gap_seconds) and last_valid_stage is not None:
            cleaned[timestamp] = last_valid_stage
            stats["short_gap_filled_seconds"] += 1
        else:
            cleaned[timestamp] = "-1"
            stats["long_gap_seconds"] += 1

    valid_seconds = sum(stage != "-1" for stage in cleaned.values())
    span_seconds = end - start + 1
    return cleaned, {
        **dict(stats),
        "start": start,
        "end": end,
        "span_seconds": span_seconds,
        "observed_seconds": len(observed),
        "valid_seconds": valid_seconds,
        "coverage_ratio": round(valid_seconds / span_seconds, 6),
    }


def _select_complete_cycle_segment(stage_map, cross_config):
    patterns = normalize_cycle_patterns(cross_config)
    audit = {
        "configured_patterns": patterns,
        "complete_cycle_count": 0,
        "selected_cycle_count": 0,
        "stage_change_limit_seconds": MAX_ADJACENT_STAGE_CHANGE_SECONDS,
    }
    if not patterns:
        audit["status"] = "cycle_patterns_unconfigured"
        return [], audit
    if not stage_map:
        audit["status"] = "extend_data_empty"
        return [], audit

    layers = compress_stage_layers(stage_map)
    cycles = find_complete_cycles(
        layers,
        patterns,
        min(stage_map),
        max(stage_map),
    )
    audit["complete_cycle_count"] = len(cycles)
    groups = group_consecutive_same_pattern_cycles(cycles)
    segments = []
    stage_change_breaks = []
    for group in groups:
        split_segments, breaks = split_cycle_group_on_stage_change(
            group,
            max_change_seconds=MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        )
        segments.extend(segment for segment in split_segments if segment)
        stage_change_breaks.extend(breaks)

    audit.update({
        "pattern_group_sizes": [len(group) for group in groups],
        "stable_segment_sizes": [len(segment) for segment in segments],
        "stage_change_break_count": len(stage_change_breaks),
    })
    if not segments:
        audit["status"] = "no_complete_stable_cycle"
        return [], audit

    def segment_key(segment):
        duration = int(segment[-1]["end"]) - int(segment[0]["start"]) + 1
        return duration, len(segment), int(segment[-1]["end"])

    selected = max(segments, key=segment_key)
    selected_start = int(selected[0]["start"])
    selected_end = int(selected[-1]["end"])
    audit.update({
        "status": "complete_cycle_segment_selected",
        "selected_cycle_count": len(selected),
        "selected_pattern": list(selected[0]["pattern"]),
        "selected_start": selected_start,
        "selected_end": selected_end,
        "selected_seconds": selected_end - selected_start + 1,
        "selected_cycle_durations": [
            int(cycle["end"]) - int(cycle["start"]) + 1
            for cycle in selected
        ],
    })
    return selected, audit


def _phase_active_directions(cross_config, stages):
    active = set()
    phase_map = cross_config.get("phase", {})
    for stage in stages:
        phase = phase_map.get(str(stage))
        if phase is None:
            continue
        active.update(PHASE_DIRECTION_MAP.get(str(phase).upper(), ()))
    return active


def _select_runtime_flow_records(flow_map, bounds=None):
    if not isinstance(flow_map, dict):
        raise TypeError("runtime flow input must be a dictionary")
    selected = {}
    stats = Counter()
    for raw_timestamp, record in flow_map.items():
        timestamp = _timestamp_seconds(raw_timestamp)
        if timestamp is None:
            stats["invalid_timestamp_records"] += 1
            continue
        stats["valid_timestamp_records"] += 1
        if bounds is not None and not bounds[0] <= timestamp <= bounds[1]:
            stats["outside_selected_interval_records"] += 1
            continue
        selected[raw_timestamp] = record
        stats["selected_records"] += 1
    return selected, dict(stats)


def _scale_flow_vectors(flow_vectors, factor):
    return {
        direction: [int(value * factor + 0.5) for value in vector]
        for direction, vector in flow_vectors.items()
    }


def allocate_from_runtime_data(
    road_id,
    flow_map_single_intersection,
    extend_map_single_intersection,
    *,
    experience_table=None,
    cross_info=None,
    saturation_ratio=DEFAULT_SATURATION_RATIO,
    left_turn_extra_seconds=0,
    safe_fallback_green_time=DEFAULT_SAFE_FALLBACK_GREEN_TIME,
    target_flow_seconds=DEFAULT_TARGET_FLOW_SECONDS,
    full_window_min_seconds=DEFAULT_FULL_WINDOW_MIN_SECONDS,
    max_stage_gap_seconds=DEFAULT_MAX_STAGE_GAP_SECONDS,
    min_green_time=1,
    max_green_time=DEFAULT_MAX_GREEN_TIME,
):
    """Allocate time from the exact ``chuli_shuju(id, flow, extend)`` shape.

    A mature runtime cache is already a ten-minute flow window and is used as
    is.  During cache warm-up, the largest stable complete-cycle segment is
    used and its lane flows are projected to ten minutes.  If no complete
    configured cycle exists, raw partial flow is retained for comparison but
    the result is explicitly marked as not quality-passed.
    """
    road_id = str(road_id)
    if experience_table is None:
        experience_table = _load_json(DEFAULT_EXPERIENCE_PATH)
    if cross_info is None:
        cross_info = _load_json(DEFAULT_CROSS_INFO_PATH)
    if road_id not in cross_info:
        raise KeyError(f"cross_info does not contain road {road_id}")
    if road_id not in experience_table:
        raise KeyError(f"experience table does not contain road {road_id}")

    cross_config = cross_info[road_id]
    stage_map, extend_stats = normalize_runtime_extend(
        road_id,
        extend_map_single_intersection,
        max_stage_gap_seconds=max_stage_gap_seconds,
    )
    selected_cycles, cycle_audit = _select_complete_cycle_segment(
        stage_map,
        cross_config,
    )

    target_flow_seconds = int(target_flow_seconds)
    full_window_min_seconds = int(full_window_min_seconds)
    extend_span_seconds = int(extend_stats.get("span_seconds", 0))
    selected_bounds = None
    normalization_factor = 1.0
    if extend_span_seconds >= full_window_min_seconds:
        normalization_mode = "full_10min_window"
        quality_passed = extend_stats.get("coverage_ratio", 0.0) >= 0.90
        active_stage_map = stage_map
    elif selected_cycles:
        selected_start = int(selected_cycles[0]["start"])
        selected_end = int(selected_cycles[-1]["end"])
        selected_bounds = (selected_start, selected_end)
        selected_seconds = selected_end - selected_start + 1
        normalization_factor = target_flow_seconds / selected_seconds
        normalization_mode = "complete_cycle_scaled_to_10min"
        quality_passed = True
        active_stage_map = {
            timestamp: stage
            for timestamp, stage in stage_map.items()
            if selected_start <= timestamp <= selected_end
        }
    else:
        normalization_mode = "partial_window_unscaled_no_complete_cycle"
        quality_passed = False
        active_stage_map = stage_map

    selected_flow, flow_selection_stats = _select_runtime_flow_records(
        flow_map_single_intersection,
        selected_bounds,
    )
    observed_vectors, observed_stats = aggregate_10min_flow(selected_flow)
    scaled_vectors = _scale_flow_vectors(observed_vectors, normalization_factor)
    directions_seen = observed_stats.get("directions_seen", [])
    allocator_input = {
        direction: scaled_vectors[direction]
        for direction in directions_seen
    }
    active_directions = _phase_active_directions(
        cross_config,
        {
            stage
            for stage in active_stage_map.values()
            if stage != "-1"
        },
    )
    flow_directions = _flow_directions(
        scaled_vectors,
        cross_config,
        set(directions_seen),
    )
    # A bad or incomplete extend stream can remove stage evidence, but it
    # cannot remove a movement that has real controlled flow in this window.
    active_directions.update(flow_directions)

    result = allocate_green_times(
        road_id,
        allocator_input,
        experience_table,
        cross_info,
        active_directions=active_directions,
        saturation_ratio=saturation_ratio,
        left_turn_extra_seconds=left_turn_extra_seconds,
        safe_fallback_green_time=safe_fallback_green_time,
        min_green_time=min_green_time,
        max_green_time=max_green_time,
    )
    result["runtime_input"] = {
        "quality_passed": quality_passed,
        "normalization_mode": normalization_mode,
        "normalization_factor": round(normalization_factor, 6),
        "target_flow_seconds": target_flow_seconds,
        "selected_flow_start": selected_bounds[0] if selected_bounds else None,
        "selected_flow_end": selected_bounds[1] if selected_bounds else None,
        "observed_flow": observed_vectors,
        "flow_selection": flow_selection_stats,
        "flow_aggregation": observed_stats,
        "flow_directions": sorted(flow_directions),
        "extend_directions": sorted(
            _phase_active_directions(
                cross_config,
                {
                    stage
                    for stage in active_stage_map.values()
                    if stage != "-1"
                },
            )
        ),
        "extend": extend_stats,
        "cycle": cycle_audit,
    }
    return result


def chuli_shuju_new(
    road_id,
    flow_map_single_intersection,
    extend_map_single_intersection,
    **kwargs,
):
    """Return only the legacy-compatible ten-position schedule vector."""
    return allocate_from_runtime_data(
        road_id,
        flow_map_single_intersection,
        extend_map_single_intersection,
        **kwargs,
    )["time_vector"]


def allocate_from_10min_flow(*args, **kwargs):
    """Readable alias for callers that describe the source data explicitly."""
    return allocate_green_times(*args, **kwargs)
