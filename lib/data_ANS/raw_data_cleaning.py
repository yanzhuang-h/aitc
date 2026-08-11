import json
import os
import tempfile
from collections import Counter, defaultdict

try:
    from lib.data_ANS.lane_policy import (
        classify_lane_type,
        is_dedicated_left,
        policy_metadata,
    )
except ModuleNotFoundError:  # Supports direct execution from this directory.
    from lane_policy import classify_lane_type, is_dedicated_left, policy_metadata


DEFAULT_MAX_STAGE_GAP_SECONDS = 3
BASE_FLOW_DIRECTIONS = ("U", "D", "L", "R")


def _time_seconds(value):
    value = int(value)
    if value > 10_000_000_000:
        value //= 1000
    if value <= 0:
        raise ValueError("timestamp must be positive")
    return value


def _write_json_atomic(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False
        ) as file:
            temp_path = file.name
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _build_detector_index(cross_info, target_cross_ids):
    detector_candidates = defaultdict(list)
    for cross_id in target_cross_ids:
        config = cross_info.get(cross_id, {})
        for detector_id, direction in config.get("jtll_ddbh", {}).items():
            detector_candidates[str(detector_id)].append((cross_id, str(direction)))

    detector_index = {}
    ambiguous = {}
    for detector_id, candidates in detector_candidates.items():
        if len(candidates) == 1:
            detector_index[detector_id] = candidates[0]
        else:
            ambiguous[detector_id] = candidates
    return detector_index, ambiguous


def _new_cross_report():
    return {
        "flow": Counter(),
        "flow_distribution": {
            "detectors": Counter(),
            "directions": Counter(),
            "lanes": Counter(),
            "movements": Counter(),
        },
        "extend": Counter(),
        "stage_coverage": {},
    }


def _flow_coverage_report(cross_id, cross_info, cross_report):
    config = cross_info.get(cross_id, {})
    distribution = cross_report["flow_distribution"]
    detector_counts = distribution["detectors"]
    direction_counts = distribution["directions"]
    lane_counts = distribution["lanes"]

    configured_detectors = {
        str(detector_id): str(direction)
        for detector_id, direction in config.get("jtll_ddbh", {}).items()
    }
    configured_directions = sorted(set(configured_detectors.values()))
    observed_directions = sorted(direction_counts)
    unconfigured_directions = sorted(
        set(BASE_FLOW_DIRECTIONS) - set(configured_directions)
    )
    missing_directions = sorted(
        set(configured_directions) - set(observed_directions)
    )
    unavailable_directions = sorted(
        set(BASE_FLOW_DIRECTIONS) - set(observed_directions)
    )
    configured_lanes = {
        f"{direction}:{lane}"
        for direction, lanes in config.get("LaneNo", {}).items()
        for lane in lanes
    }
    lane_type_counts = Counter()
    control_counts = Counter()
    non_capacity_lanes = []
    unknown_lane_types = []
    for direction, lanes in config.get("LaneNo", {}).items():
        for lane, lane_type in lanes.items():
            policy = classify_lane_type(lane_type)
            lane_type_counts[policy["lane_type"] or "<empty>"] += 1
            control_counts[policy["control"]] += 1
            lane_reference = f"{direction}:{lane}"
            if not policy["capacity_eligible"]:
                non_capacity_lanes.append(lane_reference)
            if not policy["known"]:
                unknown_lane_types.append(lane_reference)

    return {
        "configured_detector_count": len(configured_detectors),
        "observed_detector_count": len(detector_counts),
        "missing_detectors": sorted(set(configured_detectors) - set(detector_counts)),
        "configured_directions": configured_directions,
        "observed_directions": observed_directions,
        "unconfigured_directions": unconfigured_directions,
        "missing_directions": missing_directions,
        "unavailable_directions": unavailable_directions,
        "configured_lane_count": len(configured_lanes),
        "observed_lane_count": len(lane_counts),
        "lanes_without_records": sorted(configured_lanes - set(lane_counts)),
        "lane_policy": {
            **policy_metadata(),
            "configured_lane_type_counts": dict(sorted(lane_type_counts.items())),
            "configured_control_counts": dict(sorted(control_counts.items())),
            "non_capacity_lanes": sorted(non_capacity_lanes),
            "unknown_lane_type_lanes": sorted(unknown_lane_types),
        },
    }


def _clean_flow(
    flow_path,
    cross_info,
    detector_index,
    ambiguous,
    known_detector_ids,
    cross_reports,
):
    clean_flow = defaultdict(list)
    seen = set()
    totals = Counter()

    with open(flow_path, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            totals["lines"] += 1
            try:
                row = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                totals["invalid_json"] += 1
                continue

            try:
                detector_id = str(row["jtll_ddbh"])
                raw_timestamp = int(row["ts"])
                timestamp = _time_seconds(raw_timestamp)
                lane = int(row["ycsb_cdbh"])
            except (KeyError, TypeError, ValueError):
                totals["invalid_required_fields"] += 1
                continue

            if detector_id in ambiguous:
                totals["ambiguous_detector"] += 1
                continue
            mapping = detector_index.get(detector_id)
            if mapping is None:
                if detector_id in known_detector_ids:
                    totals["outside_target"] += 1
                else:
                    totals["unmapped_detector"] += 1
                continue

            cross_id, direction = mapping
            report = cross_reports[cross_id]["flow"]
            report["mapped"] += 1
            lane_map = cross_info[cross_id].get("LaneNo", {}).get(direction, {})
            lane_key = str(lane)
            if lane_key not in lane_map:
                report["invalid_lane"] += 1
                totals["invalid_lane"] += 1
                continue

            movement = str(row.get("ycsb_xsfx", "")).strip()
            expected_movement = str(lane_map[lane_key]).strip()
            if movement and expected_movement and movement != expected_movement:
                report["lane_movement_mismatch"] += 1
                totals["lane_movement_mismatch"] += 1
                movement_is_left = is_dedicated_left(movement)
                expected_is_left = is_dedicated_left(expected_movement)
                if movement_is_left or expected_is_left:
                    # Only 1A is separated into a dedicated-left experience curve.
                    # A disagreement involving it makes the split ambiguous.
                    report["dedicated_left_movement_mismatch"] += 1
                    totals["dedicated_left_movement_mismatch"] += 1
                    continue
                report["non_left_movement_mismatch_accepted"] += 1
                totals["non_left_movement_mismatch_accepted"] += 1

            event_key = (detector_id, raw_timestamp, lane, movement)
            if event_key in seen:
                report["duplicate"] += 1
                totals["duplicate"] += 1
                continue
            seen.add(event_key)

            clean_flow[cross_id].append({
                "CrossId": cross_id,
                "time": str(raw_timestamp),
                "jtll_ddbh": detector_id,
                "lan": lane,
                "ycsb_xsfx": movement,
            })
            distribution = cross_reports[cross_id]["flow_distribution"]
            distribution["detectors"][detector_id] += 1
            distribution["directions"][direction] += 1
            distribution["lanes"][f"{direction}:{lane}"] += 1
            distribution["movements"][
                movement or expected_movement or "<empty>"
            ] += 1
            report["accepted"] += 1
            totals["accepted"] += 1

    for rows in clean_flow.values():
        rows.sort(key=lambda row: _time_seconds(row["time"]))
    return dict(clean_flow), totals


def _clean_extend(
    extend_path,
    cross_info,
    target_cross_ids,
    cross_reports,
    max_stage_gap_seconds,
):
    observed = defaultdict(dict)
    conflicts = defaultdict(set)
    totals = Counter()

    with open(extend_path, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            totals["lines"] += 1
            try:
                row = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                totals["invalid_json"] += 1
                continue

            try:
                cross_id = str(row["CrossId"])
                timestamp = _time_seconds(row["time"])
                stage = str(row["curStageNo"])
            except (KeyError, TypeError, ValueError):
                totals["invalid_required_fields"] += 1
                continue

            if cross_id not in target_cross_ids:
                totals["outside_target"] += 1
                continue

            report = cross_reports[cross_id]["extend"]
            report["target_records"] += 1
            valid_stages = {str(key) for key in cross_info[cross_id].get("phase", {})}
            if stage == "-1":
                report["explicit_minus_one"] += 1
                totals["explicit_minus_one"] += 1
            elif stage not in valid_stages:
                report["invalid_stage"] += 1
                totals["invalid_stage"] += 1
                stage = "-1"

            previous = observed[cross_id].get(timestamp)
            if previous is not None:
                if previous == stage:
                    report["duplicate"] += 1
                    totals["duplicate"] += 1
                    continue
                conflicts[cross_id].add(timestamp)
                report["conflicting_second"] += 1
                totals["conflicting_second"] += 1
                observed[cross_id][timestamp] = "-1"
                continue

            observed[cross_id][timestamp] = stage
            report["accepted_observation"] += 1
            totals["accepted_observation"] += 1

    clean_extend = {}
    for cross_id in target_cross_ids:
        raw = observed.get(cross_id, {})
        if not raw:
            clean_extend[cross_id] = {}
            continue

        timestamps = sorted(raw)
        start, end = timestamps[0], timestamps[-1]
        cleaned = {}
        last_valid_stage = None
        missing_seconds = 0
        short_gap_filled_seconds = 0
        long_gap_seconds = 0
        inherited_minus_one_seconds = 0
        unresolved_minus_one_seconds = 0
        last_observed_timestamp = None

        for timestamp in range(start, end + 1):
            stage = raw.get(timestamp)
            if stage is not None:
                last_observed_timestamp = timestamp
                if stage != "-1":
                    last_valid_stage = stage
                    cleaned[timestamp] = stage
                else:
                    if last_valid_stage is not None:
                        cleaned[timestamp] = last_valid_stage
                        inherited_minus_one_seconds += 1
                    else:
                        cleaned[timestamp] = "-1"
                        unresolved_minus_one_seconds += 1
                continue

            missing_seconds += 1
            distance = (
                timestamp - last_observed_timestamp
                if last_observed_timestamp is not None
                else max_stage_gap_seconds + 1
            )
            if distance <= max_stage_gap_seconds and last_valid_stage is not None:
                cleaned[timestamp] = last_valid_stage
                short_gap_filled_seconds += 1
            else:
                cleaned[timestamp] = "-1"
                long_gap_seconds += 1

        total_seconds = end - start + 1
        valid_seconds = sum(stage != "-1" for stage in cleaned.values())
        cross_reports[cross_id]["stage_coverage"] = {
            "start": start,
            "end": end,
            "total_seconds": total_seconds,
            "observed_seconds": len(raw),
            "valid_seconds": valid_seconds,
            "coverage_ratio": round(valid_seconds / total_seconds, 6),
            "missing_seconds": missing_seconds,
            "short_gap_filled_seconds": short_gap_filled_seconds,
            "long_gap_seconds": long_gap_seconds,
            "inherited_minus_one_seconds": inherited_minus_one_seconds,
            "unresolved_minus_one_seconds": unresolved_minus_one_seconds,
            "conflicting_seconds": len(conflicts.get(cross_id, set())),
        }
        clean_extend[cross_id] = cleaned

    return clean_extend, totals


def clean_training_inputs(
    flow_path,
    extend_path,
    cross_info,
    target_cross_ids=None,
    max_stage_gap_seconds=DEFAULT_MAX_STAGE_GAP_SECONDS,
    report_path=None,
):
    if target_cross_ids is None:
        target_cross_ids = set(cross_info)
    else:
        target_cross_ids = {str(value) for value in target_cross_ids}
    target_cross_ids &= set(cross_info)

    detector_index, ambiguous = _build_detector_index(cross_info, target_cross_ids)
    known_detector_ids = {
        str(detector_id)
        for config in cross_info.values()
        for detector_id in config.get("jtll_ddbh", {})
    }
    cross_reports = defaultdict(_new_cross_report)
    clean_flow, flow_totals = _clean_flow(
        flow_path,
        cross_info,
        detector_index,
        ambiguous,
        known_detector_ids,
        cross_reports,
    )
    clean_extend, extend_totals = _clean_extend(
        extend_path,
        cross_info,
        target_cross_ids,
        cross_reports,
        max_stage_gap_seconds,
    )

    report = {
        "flow_path": os.path.abspath(flow_path),
        "extend_path": os.path.abspath(extend_path),
        "settings": {
            "max_stage_gap_seconds": max_stage_gap_seconds,
            "target_cross_count": len(target_cross_ids),
        },
        "ambiguous_detectors": ambiguous,
        "totals": {
            "flow": dict(flow_totals),
            "extend": dict(extend_totals),
        },
        "crosses": {
            cross_id: {
                "flow": dict(cross_reports[cross_id]["flow"]),
                "flow_distribution": {
                    name: dict(counter)
                    for name, counter in cross_reports[cross_id][
                        "flow_distribution"
                    ].items()
                },
                "flow_coverage": _flow_coverage_report(
                    cross_id,
                    cross_info,
                    cross_reports[cross_id],
                ),
                "extend": dict(cross_reports[cross_id]["extend"]),
                "stage_coverage": cross_reports[cross_id]["stage_coverage"],
            }
            for cross_id in sorted(target_cross_ids)
        },
    }
    if report_path:
        _write_json_atomic(report_path, report)
    return clean_flow, clean_extend, report


def clean_stage_inputs(
    extend_path,
    cross_info,
    target_cross_ids=None,
    max_stage_gap_seconds=DEFAULT_MAX_STAGE_GAP_SECONDS,
    report_path=None,
):
    """Clean stage observations without scanning an unrelated flow file."""
    if target_cross_ids is None:
        target_cross_ids = set(cross_info)
    else:
        target_cross_ids = {str(value) for value in target_cross_ids}

    unknown_cross_ids = sorted(target_cross_ids - set(cross_info))
    if unknown_cross_ids:
        raise ValueError(
            f"cross_info does not contain target crosses: {unknown_cross_ids}"
        )

    cross_reports = defaultdict(_new_cross_report)
    clean_extend, extend_totals = _clean_extend(
        extend_path,
        cross_info,
        target_cross_ids,
        cross_reports,
        max_stage_gap_seconds,
    )
    report = {
        "extend_path": os.path.abspath(extend_path),
        "settings": {
            "max_stage_gap_seconds": max_stage_gap_seconds,
            "target_cross_count": len(target_cross_ids),
        },
        "totals": dict(extend_totals),
        "crosses": {
            cross_id: {
                "extend": dict(cross_reports[cross_id]["extend"]),
                "stage_coverage": cross_reports[cross_id]["stage_coverage"],
            }
            for cross_id in sorted(target_cross_ids)
        },
    }
    if report_path:
        _write_json_atomic(report_path, report)
    return clean_extend, report
