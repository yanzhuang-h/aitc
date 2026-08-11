"""Evaluate normalized post-control observations before they re-enter the pool."""

import argparse
import json
import math
import os
import tempfile
from collections import Counter, defaultdict

try:
    from lib.data_ANS.experience_candidate_audit import ExperienceCandidateAudit
    from lib.data_ANS.lane_policy import (
        configured_movement_lane_policy,
        policy_metadata,
    )
except ModuleNotFoundError:  # Supports direct ``python experience_feedback.py``.
    from experience_candidate_audit import ExperienceCandidateAudit
    from lane_policy import configured_movement_lane_policy, policy_metadata


LANE_COUNT = 10
VALID_DIRECTIONS = {"U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL"}


def _load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _write_json_atomic(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            delete=False,
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


def _normalize_vector(vector):
    if not isinstance(vector, list) or len(vector) != LANE_COUNT:
        raise ValueError("observed_flow must contain exactly 10 lane values")
    result = []
    for value in vector:
        if isinstance(value, bool):
            raise ValueError("lane values must be integers")
        number = int(value)
        if number < 0 or number != value:
            raise ValueError("lane values must be non-negative integers")
        result.append(number)
    return result


def _movement_lane_configuration(cross_info, road_id, direction):
    selection = configured_movement_lane_policy(
        cross_info.get(road_id, {}),
        direction,
        LANE_COUNT,
    )
    return selection["eligible"], selection["excluded"]


def _movement_lanes(cross_info, road_id, direction):
    lanes, _ = _movement_lane_configuration(cross_info, road_id, direction)
    return lanes


def assess_capacity_observation(observation, table, cross_info, saturation_ratio=0.80):
    """Classify one observed 10-minute window without treating demand as capacity."""
    try:
        road_id = str(observation.get("CrossId", observation.get("road_id")))
        direction = str(observation["direction"])
        green_time = str(int(observation["actual_green_time"]))
        observed_flow = _normalize_vector(observation["observed_flow"])
    except (KeyError, TypeError, ValueError) as error:
        return {"status": "rejected_invalid_observation", "reason": str(error)}

    result = {
        "CrossId": road_id,
        "direction": direction,
        "actual_green_time": int(green_time),
        "experience_release_id": observation.get("experience_release_id"),
        "source_date": observation.get("source_date"),
        "source_window_start": observation.get("source_window_start"),
        "observed_lane_flow": observed_flow,
    }
    if direction not in VALID_DIRECTIONS:
        result.update({"status": "rejected_invalid_direction", "reason": direction})
        return result
    if road_id not in table or direction not in table[road_id]:
        result.update({"status": "not_in_active_table"})
        return result
    expected_vector = table[road_id][direction].get(green_time)
    if expected_vector is None:
        result.update({"status": "missing_green_time_point"})
        return result

    try:
        expected_flow = _normalize_vector(expected_vector)
    except ValueError as error:
        result.update({"status": "invalid_active_table", "reason": str(error)})
        return result

    configured_lanes, excluded_non_capacity = _movement_lane_configuration(
        cross_info,
        road_id,
        direction,
    )
    result["lane_policy"] = policy_metadata()
    result["excluded_non_capacity_lane_indexes"] = sorted(
        excluded_non_capacity
    )
    result["excluded_uncontrolled_lane_indexes"] = sorted(
        lane
        for lane, details in excluded_non_capacity.items()
        if details["control"] == "uncontrolled"
    )
    result["excluded_unverified_lane_indexes"] = sorted(
        lane
        for lane, details in excluded_non_capacity.items()
        if details["control"] == "unverified"
    )
    if not configured_lanes:
        status = (
            "no_controlled_capacity_lanes"
            if excluded_non_capacity
            else "missing_lane_configuration"
        )
        result.update({"status": status})
        return result

    lanes = set(configured_lanes)
    requested_lanes = observation.get("capacity_lane_indexes")
    if requested_lanes is not None:
        if not isinstance(requested_lanes, list):
            result.update({"status": "invalid_capacity_lane_indexes"})
            return result
        try:
            requested_lanes = {int(lane) for lane in requested_lanes}
        except (TypeError, ValueError):
            result.update({"status": "invalid_capacity_lane_indexes"})
            return result
        if not requested_lanes or not requested_lanes <= configured_lanes:
            result.update({"status": "invalid_capacity_lane_indexes"})
            return result
        lanes = requested_lanes

    expected_total = sum(expected_flow[lane] for lane in lanes)
    observed_total = sum(observed_flow[lane] for lane in lanes)
    result.update(
        {
            "lane_indexes": sorted(lanes),
            "raw_observed_lane_flow": observed_flow,
            "observed_lane_flow": [
                value if index in lanes else 0
                for index, value in enumerate(observed_flow)
            ],
            "expected_capacity": expected_total,
            "observed_flow": observed_total,
            "utilization": (
                round(observed_total / expected_total, 4)
                if expected_total > 0
                else None
            ),
            "capacity_error": observed_total - expected_total,
        }
    )

    if observation.get("quality_gate_passed") is not True:
        result["status"] = "rejected_quality_gate"
    elif observation.get("control_executed") is not True:
        result["status"] = "unconfirmed_control_execution"
    elif observation.get("downstream_blocked") is True:
        result["status"] = "downstream_blocked"
    elif observation.get("downstream_blocked") is not False:
        # Missing downstream evidence must not silently be treated as clear.
        result["status"] = "downstream_state_unknown"
    else:
        saturation_confirmed = observation.get(
            "saturation_confirmed",
            observation.get("queue_saturated"),
        )
        if saturation_confirmed is None:
            result["status"] = "saturation_state_unknown"
        elif saturation_confirmed is not True:
            result["status"] = "demand_limited"
        elif expected_total <= 0:
            result["status"] = "zero_expected_capacity"
        elif observed_total < math.ceil(expected_total * float(saturation_ratio)):
            result["status"] = "under_saturated"
        else:
            result["status"] = "qualified_capacity_sample"
    return result


def summarize_feedback(assessments):
    summary = Counter()
    qualified_by_point = defaultdict(list)
    for record in assessments:
        status = record.get("status", "unknown")
        summary[status] += 1
        if status == "qualified_capacity_sample":
            key = (
                record.get("CrossId"),
                record.get("direction"),
                record.get("actual_green_time"),
            )
            qualified_by_point[key].append(record)

    points = {}
    for key, records in sorted(qualified_by_point.items()):
        observed = [record["observed_flow"] for record in records]
        expected = [record["expected_capacity"] for record in records]
        points["/".join(map(str, key))] = {
            "qualified_samples": len(records),
            "mean_observed_flow": round(sum(observed) / len(observed), 2),
            "mean_expected_capacity": round(sum(expected) / len(expected), 2),
            "mean_capacity_error": round(
                sum(record["capacity_error"] for record in records) / len(records),
                2,
            ),
        }

    return {
        "summary": dict(summary),
        "qualified_points": points,
    }


def evaluate_feedback_records(records, table, cross_info, saturation_ratio=0.80):
    assessments = [
        assess_capacity_observation(
            record,
            table,
            cross_info,
            saturation_ratio=saturation_ratio,
        )
        for record in records
    ]
    return {"assessments": assessments, **summarize_feedback(assessments)}


def build_qualified_candidate_samples(assessments):
    """Convert only proven-capacity feedback into the normal candidate schema."""
    candidates = {
        "scope": "qualified_runtime_feedback",
        "selection_changed": False,
        "roads": {},
    }
    stats = Counter()
    for assessment in assessments:
        if assessment.get("status") != "qualified_capacity_sample":
            stats["excluded_non_capacity_observation"] += 1
            continue
        source_date = assessment.get("source_date")
        source_window_start = assessment.get("source_window_start")
        if source_date in (None, "") or source_window_start is None:
            stats["excluded_missing_source_window"] += 1
            continue

        road_id = str(assessment["CrossId"])
        direction = assessment["direction"]
        green_time = str(int(assessment["actual_green_time"]))
        release_id = assessment.get("experience_release_id") or "unknown-release"
        source_id = (
            f"feedback:{release_id}:{road_id}:{direction}:{green_time}:"
            f"{source_date}:{int(source_window_start)}"
        )
        metadata = {
            "source": "runtime_feedback",
            "experience_release_id": release_id,
            "expected_capacity": assessment["expected_capacity"],
            "observed_flow": assessment["observed_flow"],
            "utilization": assessment["utilization"],
            "capacity_error": assessment["capacity_error"],
        }
        candidates["roads"].setdefault(road_id, {"directions": {}})[
            "directions"
        ].setdefault(direction, {}).setdefault(green_time, []).append(
            {
                "date": str(source_date),
                "window_start": int(source_window_start),
                "source_id": source_id,
                "flow": list(assessment["observed_lane_flow"]),
                "metadata": metadata,
            }
        )
        stats["qualified_samples"] += 1

    stats.setdefault("qualified_samples", 0)
    stats.setdefault("excluded_non_capacity_observation", 0)
    stats.setdefault("excluded_missing_source_window", 0)
    return candidates, dict(stats)


def audit_candidate_samples(candidate_samples):
    """Build the same evidence report used for E_T training candidates."""
    audit = ExperienceCandidateAudit()
    for road_id, road_data in candidate_samples.get("roads", {}).items():
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
    report["scope"] = "qualified_runtime_feedback"
    return report


def _load_records(path):
    with open(path, "r", encoding="utf-8") as file:
        content = file.read().strip()
    if not content:
        return []
    if content.startswith("["):
        records = json.loads(content)
        if not isinstance(records, list):
            raise ValueError("JSON observation file must be an array")
        return records
    return [json.loads(line) for line in content.splitlines() if line.strip()]


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--cross-info", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--candidate-output")
    parser.add_argument("--audit-output")
    parser.add_argument("--saturation-ratio", type=float, default=0.80)
    args = parser.parse_args()

    report = evaluate_feedback_records(
        _load_records(args.observations),
        _load_json(args.table),
        _load_json(args.cross_info),
        saturation_ratio=args.saturation_ratio,
    )
    _write_json_atomic(args.output, report)
    if args.candidate_output or args.audit_output:
        candidates, candidate_stats = build_qualified_candidate_samples(
            report["assessments"]
        )
        report["candidate_conversion"] = candidate_stats
        _write_json_atomic(args.output, report)
        if args.candidate_output:
            _write_json_atomic(args.candidate_output, candidates)
        if args.audit_output:
            _write_json_atomic(args.audit_output, audit_candidate_samples(candidates))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
