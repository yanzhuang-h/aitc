"""Normalize cleaned flow, actual stages, and queue records into feedback samples.

The output is intentionally observational.  Stage telemetry proves that a signal
state was observed, but it does not prove that a specific released experience
table was executed.  Likewise, approach queue telemetry cannot prove that the
downstream is clear.  Those two fields therefore remain unknown until controller
ACK and downstream evidence are integrated.
"""

import argparse
import json
import os
import tempfile
from collections import Counter, defaultdict

try:
    from lib.data_ANS.cycle_quality import (
        DIRECTIONS,
        MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        MIN_CONSECUTIVE_CYCLES,
        PHASE_DIRECTION_MAP,
        WINDOW_SECONDS,
        centered_observation_bounds,
        compress_stage_layers,
        cycle_observation_expansion_decision,
        find_complete_cycles,
        group_consecutive_same_pattern_cycles,
        split_cycle_group_on_stage_change,
    )
    from lib.data_ANS.experience_candidate_audit import ExperienceCandidateAudit
    from lib.data_ANS.lane_policy import (
        classify_lane_type,
        configured_movement_lane_policy,
        policy_metadata,
        raw_movement_direction,
    )
    from lib.data_ANS.raw_data_cleaning import clean_training_inputs
except ModuleNotFoundError:  # Supports direct execution from this directory.
    from cycle_quality import (
        DIRECTIONS,
        MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        MIN_CONSECUTIVE_CYCLES,
        PHASE_DIRECTION_MAP,
        WINDOW_SECONDS,
        centered_observation_bounds,
        compress_stage_layers,
        cycle_observation_expansion_decision,
        find_complete_cycles,
        group_consecutive_same_pattern_cycles,
        split_cycle_group_on_stage_change,
    )
    from experience_candidate_audit import ExperienceCandidateAudit
    from lane_policy import (
        classify_lane_type,
        configured_movement_lane_policy,
        policy_metadata,
        raw_movement_direction,
    )
    from raw_data_cleaning import clean_training_inputs


LANE_COUNT = 10
BASE_DIRECTIONS = ("U", "D", "L", "R")
QUEUE_LOOKBACK_SECONDS = 10
TAIL_FLOW_WINDOW_SECONDS = 7
EMPTY_RELEASE_MAX_TAIL_VEHICLES = 1
LIKELY_SATURATED_MIN_TAIL_VEHICLES = 3
NEAR_CAPACITY_MAX_CLEARANCE_SECONDS = 10
MIN_NEAR_CAPACITY_GREEN_RUNS = 2
TERMINAL_DISCHARGE_TAIL_SECONDS = 3


def _write_json_atomic(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False
        ) as file:
            temporary_path = file.name
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _timestamp_seconds(value):
    timestamp = int(value)
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    if timestamp <= 0:
        raise ValueError("timestamp must be positive")
    return timestamp


def _cycle_patterns(cross_config):
    raw_patterns = cross_config.get("Cycle", [])
    if isinstance(raw_patterns, dict):
        raw_patterns = [raw_patterns]

    patterns = []
    for raw_pattern in raw_patterns:
        if isinstance(raw_pattern, dict):
            raw_pattern = raw_pattern.get("value")
        if isinstance(raw_pattern, list) and raw_pattern:
            patterns.append([str(stage) for stage in raw_pattern])
    patterns.sort(key=len, reverse=True)
    return patterns


def _movement_lane_configuration(cross_config, direction):
    selection = configured_movement_lane_policy(
        cross_config,
        direction,
        LANE_COUNT,
    )
    excluded = {
        lane: details["lane_type"]
        for lane, details in selection["excluded"].items()
    }
    return selection["eligible"], excluded


def _movement_lanes(cross_config, direction):
    lanes, _ = _movement_lane_configuration(cross_config, direction)
    return lanes


def _detector_index(cross_info, target_cross_ids):
    index = {}
    ambiguous = set()
    for cross_id in target_cross_ids:
        for detector_id, direction in cross_info[cross_id].get(
            "jtll_ddbh", {}
        ).items():
            detector_id = str(detector_id)
            value = (str(cross_id), str(direction))
            if detector_id in index and index[detector_id] != value:
                ambiguous.add(detector_id)
            else:
                index[detector_id] = value
    for detector_id in ambiguous:
        index.pop(detector_id, None)
    return index, ambiguous


def _select_nearest_three(cycles, window_start, window_end):
    target_midpoint_twice = int(window_start) + int(window_end)
    candidates = []
    for index in range(len(cycles) - MIN_CONSECUTIVE_CYCLES + 1):
        subset = cycles[index:index + MIN_CONSECUTIVE_CYCLES]
        midpoint_twice = int(subset[0]["start"]) + int(subset[-1]["end"])
        candidates.append((
            abs(midpoint_twice - target_midpoint_twice),
            int(subset[0]["start"]),
            subset,
        ))
    return list(min(candidates, key=lambda value: value[:2])[2])


def _select_stable_cycles(layers, patterns, window_start, window_end):
    cycles = find_complete_cycles(layers, patterns, window_start, window_end)
    observation_start = int(window_start)
    observation_end = int(window_end)
    expansion = cycle_observation_expansion_decision(cycles)
    if expansion["should_expand"]:
        observation_start, observation_end = centered_observation_bounds(
            window_start,
            window_end,
        )
        cycles = find_complete_cycles(
            layers,
            patterns,
            observation_start,
            observation_end,
        )

    pattern_groups = group_consecutive_same_pattern_cycles(cycles)
    structural_groups = [
        group for group in pattern_groups if len(group) >= MIN_CONSECUTIVE_CYCLES
    ]
    stable_groups = []
    stage_change_breaks = []
    for group in structural_groups:
        segments, breaks = split_cycle_group_on_stage_change(
            group,
            max_change_seconds=MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        )
        stage_change_breaks.extend(breaks)
        stable_groups.extend(
            segment
            for segment in segments
            if len(segment) >= MIN_CONSECUTIVE_CYCLES
        )

    audit = {
        "complete_cycle_count": len(cycles),
        "pattern_group_sizes": [len(group) for group in pattern_groups],
        "structural_group_count": len(structural_groups),
        "stable_group_count": len(stable_groups),
        "stage_change_limit_seconds": MAX_ADJACENT_STAGE_CHANGE_SECONDS,
        "stage_change_break_count": len(stage_change_breaks),
        "stage_change_breaks": stage_change_breaks,
        "cycle_observation_start": observation_start,
        "cycle_observation_end": observation_end,
        "cycle_observation_expanded": bool(expansion["should_expand"]),
        "cycle_observation_decision": expansion,
    }
    if not stable_groups:
        audit["status"] = "no_stable_three_cycle_group"
        return [], audit

    target_midpoint_twice = int(window_start) + int(window_end)

    def group_key(group):
        nearest_distance = min(
            abs(
                int(group[index]["start"])
                + int(group[index + MIN_CONSECUTIVE_CYCLES - 1]["end"])
                - target_midpoint_twice
            )
            for index in range(len(group) - MIN_CONSECUTIVE_CYCLES + 1)
        )
        return nearest_distance, -len(group), int(group[0]["start"])

    selected_group = min(stable_groups, key=group_key)
    selected_cycles = _select_nearest_three(
        selected_group,
        window_start,
        window_end,
    )
    audit.update({
        "status": "accepted",
        "selected_pattern": list(selected_cycles[0]["pattern"]),
        "selected_cycle_count": len(selected_cycles),
        "selected_cycle_start": int(selected_cycles[0]["start"]),
        "selected_cycle_end": int(selected_cycles[-1]["end"]),
    })
    return selected_cycles, audit


def _direction_green_times(cycles, cross_config):
    totals = {direction: 0 for direction in DIRECTIONS}
    for cycle in cycles:
        for item in cycle["items"]:
            phase_name = str(
                cross_config.get("phase", {}).get(str(item["stage"]), "")
            ).strip().upper()
            for direction in PHASE_DIRECTION_MAP.get(phase_name, ()):
                totals[direction] += int(item["duration"])
    cycle_count = len(cycles)
    return {
        direction: int(round(total / cycle_count))
        for direction, total in totals.items()
    }


def _movement_green_runs(cycles, cross_config, direction):
    """Return contiguous release intervals for one movement in each cycle."""
    runs = []
    for cycle in cycles:
        current = None
        for item in cycle["items"]:
            phase_name = str(
                cross_config.get("phase", {}).get(str(item["stage"]), "")
            ).strip().upper()
            releases_direction = direction in PHASE_DIRECTION_MAP.get(
                phase_name,
                (),
            )
            if releases_direction:
                if current and int(item["start"]) == current["end"] + 1:
                    current["end"] = int(item["end"])
                else:
                    if current:
                        runs.append(current)
                    current = {
                        "start": int(item["start"]),
                        "end": int(item["end"]),
                    }
            elif current:
                runs.append(current)
                current = None
        if current:
            runs.append(current)
    return runs


def _complete_flow_window_green_runs(green_runs, window_start, window_end):
    """Exclude expanded-observation cycles that have no matching flow window."""
    return [
        run
        for run in green_runs
        if int(window_start) <= run["start"] and run["end"] <= int(window_end)
    ]


def _split_flow(flow_records, cross_config):
    vectors = {direction: [0] * LANE_COUNT for direction in DIRECTIONS}
    detector_map = {
        str(detector_id): str(direction)
        for detector_id, direction in cross_config.get("jtll_ddbh", {}).items()
    }
    lane_maps = cross_config.get("LaneNo", {})
    for record in flow_records:
        direction = detector_map.get(str(record.get("jtll_ddbh")))
        try:
            lane = int(record["lan"])
        except (KeyError, TypeError, ValueError):
            continue
        if direction not in BASE_DIRECTIONS or not 0 <= lane < LANE_COUNT:
            continue
        lane_type = str(lane_maps.get(direction, {}).get(str(lane), "")).upper()
        if not lane_type:
            continue
        target = raw_movement_direction(direction, lane_type)
        if target is None:
            continue
        vectors[target][lane] += 1
    return vectors


def _movement_events(flow_records, cross_config):
    events = {direction: defaultdict(list) for direction in DIRECTIONS}
    detector_map = {
        str(detector_id): str(direction)
        for detector_id, direction in cross_config.get("jtll_ddbh", {}).items()
    }
    lane_maps = cross_config.get("LaneNo", {})
    for record in flow_records:
        direction = detector_map.get(str(record.get("jtll_ddbh")))
        try:
            lane = int(record["lan"])
            timestamp = _timestamp_seconds(record["time"])
        except (KeyError, TypeError, ValueError):
            continue
        if direction not in BASE_DIRECTIONS or not 0 <= lane < LANE_COUNT:
            continue
        lane_type = str(lane_maps.get(direction, {}).get(str(lane), "")).upper()
        if not lane_type:
            continue
        target = raw_movement_direction(direction, lane_type)
        if target is None:
            continue
        events[target][lane].append(timestamp)
    for direction_events in events.values():
        for timestamps in direction_events.values():
            timestamps.sort()
    return events


def _flow_discharge_evidence(
    events,
    direction,
    lanes,
    green_runs,
    excluded_uncontrolled=None,
):
    """Classify lane-level terminal discharge without treating queue=0 as fact."""
    lane_results = {}
    not_near_capacity_lanes = []
    near_capacity_lanes = []
    strict_likely_saturated_lanes = []
    indeterminate_lanes = []
    for lane in sorted(lanes):
        lane_events = events.get(direction, {}).get(lane, [])
        run_results = []
        lane_near_capacity = len(green_runs) >= MIN_NEAR_CAPACITY_GREEN_RUNS
        lane_strict_likely_saturated = bool(green_runs)
        for run in green_runs:
            discharge = [
                timestamp
                for timestamp in lane_events
                if run["start"] <= timestamp <= run["end"]
            ]
            duration = run["end"] - run["start"] + 1
            tail_idle_seconds = (
                run["end"] - discharge[-1] if discharge else duration
            )
            tail_window_start = max(
                run["start"],
                run["end"] - TAIL_FLOW_WINDOW_SECONDS + 1,
            )
            tail_window_vehicle_count = sum(
                tail_window_start <= timestamp <= run["end"]
                for timestamp in discharge
            )
            has_full_tail_window = duration >= TAIL_FLOW_WINDOW_SECONDS
            low_tail_flow = (
                has_full_tail_window
                and tail_window_vehicle_count <= EMPTY_RELEASE_MAX_TAIL_VEHICLES
            )
            empty_release = low_tail_flow
            likely_saturated = (
                has_full_tail_window
                and tail_window_vehicle_count
                >= LIKELY_SATURATED_MIN_TAIL_VEHICLES
            )
            near_capacity = bool(discharge) and (
                tail_idle_seconds <= NEAR_CAPACITY_MAX_CLEARANCE_SECONDS
            )
            terminal_discharge = bool(discharge) and (
                tail_idle_seconds <= TERMINAL_DISCHARGE_TAIL_SECONDS
            )
            lane_near_capacity = lane_near_capacity and near_capacity
            lane_strict_likely_saturated = (
                lane_strict_likely_saturated and likely_saturated
            )
            run_results.append({
                "start": run["start"],
                "end": run["end"],
                "duration": duration,
                "flow_count": len(discharge),
                "tail_idle_seconds": tail_idle_seconds,
                "tail_window_seconds": TAIL_FLOW_WINDOW_SECONDS,
                "tail_window_vehicle_count": tail_window_vehicle_count,
                "low_tail_flow": low_tail_flow,
                "empty_release": empty_release,
                "likely_saturated": likely_saturated,
                "near_capacity": near_capacity,
                "terminal_discharge": terminal_discharge,
            })
        lane_results[str(lane)] = run_results
        if lane_near_capacity:
            near_capacity_lanes.append(lane)
            if lane_strict_likely_saturated:
                strict_likely_saturated_lanes.append(lane)
        elif run_results:
            not_near_capacity_lanes.append(lane)
        else:
            indeterminate_lanes.append(lane)

    if not lanes:
        status = "missing_movement_lane_configuration"
        saturation_confirmed = None
    elif not green_runs:
        status = "no_green_run_evidence"
        saturation_confirmed = None
    elif len(near_capacity_lanes) == len(lanes):
        status = "near_capacity_all_lanes"
        # Flow alone cannot distinguish standing queue from perfectly timed arrivals.
        saturation_confirmed = None
    elif near_capacity_lanes:
        status = "partial_near_capacity_lanes"
        saturation_confirmed = None
    elif len(not_near_capacity_lanes) == len(lanes):
        status = "not_near_capacity_release"
        saturation_confirmed = False
    else:
        status = "indeterminate_discharge"
        saturation_confirmed = None
    excluded_non_capacity = excluded_uncontrolled or {}
    excluded_uncontrolled = {
        lane: lane_type
        for lane, lane_type in excluded_non_capacity.items()
        if classify_lane_type(lane_type)["control"] == "uncontrolled"
    }
    excluded_unverified = {
        lane: lane_type
        for lane, lane_type in excluded_non_capacity.items()
        if classify_lane_type(lane_type)["control"] == "unverified"
    }
    return {
        "saturation_confirmed": saturation_confirmed,
        "saturation_state": status,
        "tail_flow_window_seconds": TAIL_FLOW_WINDOW_SECONDS,
        "empty_release_max_tail_vehicles": EMPTY_RELEASE_MAX_TAIL_VEHICLES,
        "likely_saturated_min_tail_vehicles": LIKELY_SATURATED_MIN_TAIL_VEHICLES,
        "near_capacity_max_clearance_seconds": (
            NEAR_CAPACITY_MAX_CLEARANCE_SECONDS
        ),
        "min_near_capacity_green_runs": MIN_NEAR_CAPACITY_GREEN_RUNS,
        "terminal_discharge_tail_seconds": TERMINAL_DISCHARGE_TAIL_SECONDS,
        "not_near_capacity_lane_indexes": not_near_capacity_lanes,
        "near_capacity_lane_indexes": near_capacity_lanes,
        "strict_likely_saturated_lane_indexes": strict_likely_saturated_lanes,
        "indeterminate_lane_indexes": indeterminate_lanes,
        "excluded_uncontrolled_lane_indexes": sorted(excluded_uncontrolled),
        "excluded_uncontrolled_lanes": {
            str(lane): lane_type
            for lane, lane_type in sorted(excluded_uncontrolled.items())
        },
        "excluded_non_capacity_lane_indexes": sorted(excluded_non_capacity),
        "excluded_non_capacity_lanes": {
            str(lane): lane_type
            for lane, lane_type in sorted(excluded_non_capacity.items())
        },
        "excluded_unverified_lane_indexes": sorted(excluded_unverified),
        "lanes": lane_results,
    }


def _read_queue_records(
    queue_path,
    cross_info,
    target_cross_ids,
    start_time,
    end_time,
):
    detector_index, ambiguous = _detector_index(cross_info, target_cross_ids)
    values = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    totals = Counter()
    minimum_time = int(start_time) - QUEUE_LOOKBACK_SECONDS
    with open(queue_path, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            totals["lines"] += 1
            try:
                row = json.loads(line)
                detector_id = str(row["jtll_ddbh"])
                timestamp = _timestamp_seconds(row["start_time"])
                lane_rows = row["car_nums"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                totals["invalid_json_or_fields"] += 1
                continue
            if timestamp < minimum_time or timestamp > int(end_time):
                totals["outside_time_range"] += 1
                continue
            if detector_id in ambiguous:
                totals["ambiguous_detector"] += 1
                continue
            mapping = detector_index.get(detector_id)
            if mapping is None:
                totals["unmapped_detector"] += 1
                continue
            if not isinstance(lane_rows, list):
                totals["invalid_lane_rows"] += 1
                continue
            cross_id, direction = mapping
            lane_map = cross_info[cross_id].get("LaneNo", {}).get(direction, {})
            for lane_row in lane_rows:
                try:
                    lane = int(lane_row["ycsb_cdbh"])
                    queue = int(lane_row["queue"])
                except (KeyError, TypeError, ValueError):
                    totals["invalid_lane_value"] += 1
                    continue
                if str(lane) not in lane_map or not 0 <= lane < LANE_COUNT:
                    totals["invalid_lane"] += 1
                    continue
                if queue < 0:
                    totals["unknown_queue_value"] += 1
                    continue
                previous = values[cross_id][direction][lane].get(timestamp)
                if previous is not None and previous != queue:
                    values[cross_id][direction][lane][timestamp] = None
                    totals["conflicting_lane_second"] += 1
                    continue
                values[cross_id][direction][lane][timestamp] = queue
                totals["accepted_lane_samples"] += 1
    return values, dict(totals)


def _full_window_bounds(start_time, end_time):
    first = ((int(start_time) + WINDOW_SECONDS - 1) // WINDOW_SECONDS) * WINDOW_SECONDS
    last = ((int(end_time) - WINDOW_SECONDS + 1) // WINDOW_SECONDS) * WINDOW_SECONDS
    if first > last:
        return []
    return list(range(first, last + 1, WINDOW_SECONDS))


def normalize_raw_feedback(
    flow_path,
    extend_path,
    queue_path,
    cross_info,
    source_date,
    start_time,
    end_time,
    target_cross_ids=None,
):
    """Return conservative feedback observations from one aligned time range."""
    if target_cross_ids is None:
        target_cross_ids = sorted(cross_info)
    target_cross_ids = sorted({str(value) for value in target_cross_ids})
    missing = sorted(set(target_cross_ids) - set(cross_info))
    if missing:
        raise ValueError(f"cross_info does not contain target crosses: {missing}")

    clean_flow, clean_extend, cleaning_report = clean_training_inputs(
        flow_path,
        extend_path,
        cross_info,
        target_cross_ids=target_cross_ids,
    )
    if queue_path:
        _, queue_report = _read_queue_records(
            queue_path,
            cross_info,
            target_cross_ids,
            start_time,
            end_time,
        )
        queue_report["used_for_saturation"] = False
    else:
        queue_report = {
            "status": "not_loaded",
            "used_for_saturation": False,
        }
    flow_by_window = defaultdict(lambda: defaultdict(list))
    for cross_id, records in clean_flow.items():
        for record in records:
            timestamp = _timestamp_seconds(record["time"])
            if int(start_time) <= timestamp <= int(end_time):
                flow_by_window[cross_id][
                    (timestamp // WINDOW_SECONDS) * WINDOW_SECONDS
                ].append(record)

    observations = []
    report = {
        "scope": "raw_feedback_normalization",
        "source_date": str(source_date),
        "time_range": {"start": int(start_time), "end": int(end_time)},
        "full_window_starts": _full_window_bounds(start_time, end_time),
        "target_cross_ids": target_cross_ids,
        "capacity_lane_policy": policy_metadata(),
        "cleaning": cleaning_report,
        "queue": queue_report,
        "summary": Counter(),
        "crosses": {},
    }

    for cross_id in target_cross_ids:
        cross_config = cross_info[cross_id]
        patterns = _cycle_patterns(cross_config)
        cross_summary = Counter()
        cross_report = {"cycle_configured": bool(patterns), "windows": []}
        layers = compress_stage_layers(clean_extend.get(cross_id, {}))
        if not patterns:
            cross_summary["missing_cycle_config"] += len(report["full_window_starts"])
        elif not layers:
            cross_summary["missing_clean_stage_data"] += len(
                report["full_window_starts"]
            )
        else:
            for window_start in report["full_window_starts"]:
                window_end = window_start + WINDOW_SECONDS - 1
                cycles, cycle_audit = _select_stable_cycles(
                    layers,
                    patterns,
                    window_start,
                    window_end,
                )
                window_report = {
                    "window_start": window_start,
                    "window_end": window_end,
                    "cycle": cycle_audit,
                }
                if not cycles:
                    cross_summary[cycle_audit["status"]] += 1
                    cross_report["windows"].append(window_report)
                    continue

                window_flow = flow_by_window[cross_id].get(window_start, [])
                flow_vectors = _split_flow(
                    window_flow,
                    cross_config,
                )
                movement_events = _movement_events(window_flow, cross_config)
                green_times = _direction_green_times(cycles, cross_config)
                window_observation_count = 0
                for direction in DIRECTIONS:
                    lanes, excluded_uncontrolled = _movement_lane_configuration(
                        cross_config,
                        direction,
                    )
                    green_time = green_times[direction]
                    if not lanes or green_time <= 0:
                        if excluded_uncontrolled and green_time > 0:
                            cross_summary[
                                "direction_without_controlled_capacity_lane"
                            ] += 1
                        continue
                    all_green_runs = _movement_green_runs(
                        cycles,
                        cross_config,
                        direction,
                    )
                    green_runs = _complete_flow_window_green_runs(
                        all_green_runs,
                        window_start,
                        window_end,
                    )
                    evidence = _flow_discharge_evidence(
                        movement_events,
                        direction,
                        lanes,
                        green_runs,
                        excluded_uncontrolled,
                    )
                    candidate_lanes = set(evidence["near_capacity_lane_indexes"])
                    observations.append({
                        "CrossId": cross_id,
                        "direction": direction,
                        "actual_green_time": green_time,
                        "observed_flow": flow_vectors[direction],
                        "quality_gate_passed": True,
                        "control_executed": None,
                        "downstream_blocked": None,
                        "saturation_confirmed": evidence["saturation_confirmed"],
                        "saturation_state": evidence["saturation_state"],
                        "capacity_lane_indexes": sorted(candidate_lanes),
                        "candidate_observed_flow": [
                            value if index in candidate_lanes else 0
                            for index, value in enumerate(flow_vectors[direction])
                        ],
                        "source_date": str(source_date),
                        "source_window_start": window_start,
                        "cycle_evidence": cycle_audit,
                        "flow_discharge_evidence": evidence,
                        "selected_green_run_count": len(all_green_runs),
                        "flow_window_green_run_count": len(green_runs),
                        "control_evidence": "actual_stage_observed_but_release_unconfirmed",
                        "downstream_evidence": "not_available_in_flow_extend_queue",
                    })
                    cross_summary["observations"] += 1
                    cross_summary[f"flow_{evidence['saturation_state']}"] += 1
                    window_observation_count += 1
                window_report["observation_count"] = window_observation_count
                cross_summary["accepted_cycle_windows"] += 1
                cross_report["windows"].append(window_report)

        report["crosses"][cross_id] = {
            "summary": dict(cross_summary),
            **cross_report,
        }
        report["summary"].update(cross_summary)

    report["summary"] = dict(report["summary"])
    report["observation_count"] = len(observations)
    return observations, report


def build_near_capacity_candidate_samples(observations):
    """Convert lane-masked historical near-capacity observations for the pool."""
    candidates = {
        "scope": "historical_near_capacity",
        "policy": {
            "max_clearance_seconds": NEAR_CAPACITY_MAX_CLEARANCE_SECONDS,
            "minimum_complete_green_runs": MIN_NEAR_CAPACITY_GREEN_RUNS,
            "record_only_near_capacity_lanes": True,
            "lane_policy": policy_metadata(),
        },
        "roads": {},
    }
    stats = Counter()
    for observation in observations:
        if observation.get("quality_gate_passed") is not True:
            stats["excluded_quality_gate"] += 1
            continue
        try:
            road_id = str(observation["CrossId"])
            direction = str(observation["direction"])
            green_time = str(int(observation["actual_green_time"]))
            window_start = int(observation["source_window_start"])
            source_date = str(observation["source_date"])
            lanes = {int(lane) for lane in observation["capacity_lane_indexes"]}
            flow = [int(value) for value in observation["candidate_observed_flow"]]
        except (KeyError, TypeError, ValueError):
            stats["excluded_invalid_observation"] += 1
            continue
        if not lanes:
            stats["excluded_no_near_capacity_lanes"] += 1
            continue
        if len(flow) != LANE_COUNT or any(value < 0 for value in flow):
            stats["excluded_invalid_flow_vector"] += 1
            continue
        if any(flow[index] for index in range(LANE_COUNT) if index not in lanes):
            stats["excluded_unmasked_lane_flow"] += 1
            continue

        evidence = observation.get("flow_discharge_evidence", {})
        source_id = (
            f"near-capacity:{road_id}:{direction}:{green_time}:"
            f"{source_date}:{window_start}"
        )
        metadata = {
            "source": "historical_near_capacity",
            "capacity_lane_indexes": sorted(lanes),
            "near_capacity_max_clearance_seconds": evidence.get(
                "near_capacity_max_clearance_seconds"
            ),
            "flow_window_green_run_count": observation.get(
                "flow_window_green_run_count"
            ),
            "strict_likely_saturated_lane_indexes": evidence.get(
                "strict_likely_saturated_lane_indexes", []
            ),
            "excluded_uncontrolled_lane_indexes": evidence.get(
                "excluded_uncontrolled_lane_indexes", []
            ),
            "excluded_non_capacity_lane_indexes": evidence.get(
                "excluded_non_capacity_lane_indexes", []
            ),
            "excluded_unverified_lane_indexes": evidence.get(
                "excluded_unverified_lane_indexes", []
            ),
        }
        candidates["roads"].setdefault(road_id, {"directions": {}})[
            "directions"
        ].setdefault(direction, {}).setdefault(green_time, []).append({
            "date": source_date,
            "window_start": window_start,
            "source_id": source_id,
            "flow": flow,
            "metadata": metadata,
        })
        stats["accepted_samples"] += 1
        stats["recorded_lanes"] += len(lanes)

    for key in (
        "accepted_samples",
        "recorded_lanes",
        "excluded_quality_gate",
        "excluded_invalid_observation",
        "excluded_no_near_capacity_lanes",
        "excluded_invalid_flow_vector",
        "excluded_unmasked_lane_flow",
    ):
        stats.setdefault(key, 0)
    return candidates, dict(stats)


def audit_near_capacity_candidate_samples(candidates):
    audit = ExperienceCandidateAudit()
    for road_id, road_data in candidates.get("roads", {}).items():
        for direction, time_map in road_data.get("directions", {}).items():
            for green_time, samples in time_map.items():
                for sample in samples:
                    metadata = dict(sample.get("metadata") or {})
                    metadata["source_id"] = sample.get("source_id")
                    audit.add_experience(
                        road_id,
                        {direction: {green_time: sample["flow"]}},
                        data_day=sample.get("date"),
                        window_start=sample.get("window_start"),
                        metadata=metadata,
                    )
    report = audit.build_report()
    report["scope"] = "historical_near_capacity"
    return report


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow", required=True)
    parser.add_argument("--extend", required=True)
    parser.add_argument("--queue")
    parser.add_argument("--cross-info", required=True)
    parser.add_argument("--source-date", required=True)
    parser.add_argument("--start-time", required=True, type=int)
    parser.add_argument("--end-time", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--road-ids", default="")
    parser.add_argument("--candidate-output")
    parser.add_argument("--candidate-audit-output")
    args = parser.parse_args()

    targets = [
        value.strip() for value in args.road_ids.split(",") if value.strip()
    ] or None
    observations, report = normalize_raw_feedback(
        args.flow,
        args.extend,
        args.queue,
        _load_json(args.cross_info),
        args.source_date,
        args.start_time,
        args.end_time,
        target_cross_ids=targets,
    )
    if args.candidate_output or args.candidate_audit_output:
        candidates, candidate_stats = build_near_capacity_candidate_samples(
            observations
        )
        report["candidate_conversion"] = candidate_stats
        if args.candidate_output:
            _write_json_atomic(args.candidate_output, candidates)
        if args.candidate_audit_output:
            _write_json_atomic(
                args.candidate_audit_output,
                audit_near_capacity_candidate_samples(candidates),
            )
    _write_json_atomic(args.output, observations)
    _write_json_atomic(args.report, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
