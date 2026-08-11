import argparse
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from statistics import median

try:
    from lib.data_ANS.raw_data_cleaning import clean_stage_inputs
except ModuleNotFoundError:
    from raw_data_cleaning import clean_stage_inputs


WINDOW_SECONDS = 600
CYCLE_OBSERVATION_WINDOW_SECONDS = 900
LONG_CYCLE_THRESHOLD_SECONDS = 200
MIN_CONSECUTIVE_CYCLES = 3
MIN_SECONDS_TOLERANCE = 5
MAX_ADJACENT_STAGE_CHANGE_SECONDS = 8
DIRECTIONS = ("U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL")
PHASE_DIRECTION_MAP = {
    "UD": ("U", "D"),
    "LR": ("L", "R"),
    "UDL": ("UTL", "DTL"),
    "LRL": ("LTL", "RTL"),
    "U": ("U", "UTL"),
    "D": ("D", "DTL"),
    "L": ("L", "LTL"),
    "R": ("R", "RTL"),
    "LTD": ("LTL", "D"),
}


def centered_observation_bounds(
    window_start,
    window_end,
    target_seconds=CYCLE_OBSERVATION_WINDOW_SECONDS,
):
    """Expand a flow window evenly without changing the flow boundaries."""
    window_start = int(window_start)
    window_end = int(window_end)
    current_seconds = window_end - window_start + 1
    extra_seconds = max(0, int(target_seconds) - current_seconds)
    before_seconds = extra_seconds // 2
    after_seconds = extra_seconds - before_seconds
    return window_start - before_seconds, window_end + after_seconds


def cycle_observation_expansion_decision(
    cycles,
    minimum_cycles=MIN_CONSECUTIVE_CYCLES,
    long_cycle_threshold_seconds=LONG_CYCLE_THRESHOLD_SECONDS,
):
    durations = [
        sum(int(item["duration"]) for item in cycle.get("items", []))
        for cycle in cycles
    ]
    representative_duration = (
        float(median(durations)) if durations else None
    )

    if len(cycles) >= int(minimum_cycles):
        reason = "enough_cycles_in_flow_window"
        should_expand = False
    elif representative_duration is None:
        reason = "no_complete_cycle_for_duration_judgment"
        should_expand = False
    elif representative_duration > int(long_cycle_threshold_seconds):
        reason = "long_cycle_over_threshold"
        should_expand = True
    else:
        reason = "cycle_not_over_threshold"
        should_expand = False

    return {
        "should_expand": should_expand,
        "reason": reason,
        "threshold_seconds": int(long_cycle_threshold_seconds),
        "initial_cycle_count": len(cycles),
        "initial_cycle_durations": durations,
        "representative_cycle_duration_seconds": representative_duration,
    }


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


def normalize_cycle_patterns(cross_config):
    patterns = []
    for pattern in cross_config.get("Cycle", []):
        if isinstance(pattern, list) and pattern:
            patterns.append([str(stage) for stage in pattern])
    patterns.sort(key=len, reverse=True)
    return patterns


def compress_stage_layers(stage_map):
    if not stage_map:
        return []

    layers = []
    current_stage = None
    current_start = None
    previous_timestamp = None
    for timestamp, stage in sorted(stage_map.items()):
        timestamp = int(timestamp)
        stage = str(stage)
        if current_stage is None:
            current_stage = stage
            current_start = timestamp
            previous_timestamp = timestamp
            continue

        if stage == current_stage and timestamp == previous_timestamp + 1:
            previous_timestamp = timestamp
            continue

        layers.append({
            "stage": current_stage,
            "start": current_start,
            "end": previous_timestamp,
            "duration": previous_timestamp - current_start + 1,
        })
        current_stage = stage
        current_start = timestamp
        previous_timestamp = timestamp

    layers.append({
        "stage": current_stage,
        "start": current_start,
        "end": previous_timestamp,
        "duration": previous_timestamp - current_start + 1,
    })
    last_index = len(layers) - 1
    for index, layer in enumerate(layers):
        layer["layer_index"] = index
        layer["data_boundary_partial"] = index in (0, last_index)
    return layers


def find_complete_cycles(layers, patterns, window_start, window_end):
    window_layers = [
        layer
        for layer in layers
        if layer["start"] >= window_start and layer["end"] <= window_end
    ]
    cycles = []
    index = 0
    while index < len(window_layers):
        matched = False
        for pattern in patterns:
            size = len(pattern)
            candidate = window_layers[index:index + size]
            if len(candidate) != size:
                continue
            if [item["stage"] for item in candidate] != pattern:
                continue
            if any(item["data_boundary_partial"] for item in candidate):
                continue
            cycles.append({
                "pattern": pattern,
                "start": candidate[0]["start"],
                "end": candidate[-1]["end"],
                "start_layer_index": candidate[0]["layer_index"],
                "end_layer_index": candidate[-1]["layer_index"],
                "items": candidate,
            })
            index += size
            matched = True
            break
        if not matched:
            index += 1
    return cycles


def group_consecutive_same_pattern_cycles(cycles):
    groups = []
    current = []
    for cycle in cycles:
        if not current:
            current = [cycle]
            continue
        previous = current[-1]
        is_consecutive = (
            cycle["start_layer_index"] == previous["end_layer_index"] + 1
        )
        if cycle["pattern"] == previous["pattern"] and is_consecutive:
            current.append(cycle)
        else:
            groups.append(current)
            current = [cycle]
    if current:
        groups.append(current)
    return groups


def split_cycle_group_on_stage_change(
    group,
    max_change_seconds=MAX_ADJACENT_STAGE_CHANGE_SECONDS,
):
    if not group:
        return [], []

    segments = []
    breaks = []
    current = [group[0]]
    for cycle in group[1:]:
        previous = current[-1]
        changed_stages = []
        for position, (before, after) in enumerate(zip(
            previous["items"],
            cycle["items"],
        )):
            delta = abs(int(after["duration"]) - int(before["duration"]))
            if delta > max_change_seconds:
                changed_stages.append({
                    "position": position,
                    "stage": str(after["stage"]),
                    "delta_seconds": delta,
                })
        if changed_stages:
            segments.append(current)
            breaks.append({
                "previous_cycle_start": previous["start"],
                "current_cycle_start": cycle["start"],
                "changed_stages": changed_stages,
            })
            current = [cycle]
        else:
            current.append(cycle)
    segments.append(current)
    return segments, breaks


def _cycle_sample(
    cycle,
    road_id,
    data_day,
    window_start,
    phase_map,
    group_index,
    cycle_index_in_group,
    group_size,
    observation_start,
    observation_end,
    observation_expanded,
):
    direction_times = {direction: 0 for direction in DIRECTIONS}
    for item in cycle["items"]:
        phase_name = phase_map.get(str(item["stage"]))
        for direction in PHASE_DIRECTION_MAP.get(phase_name, ()):
            direction_times[direction] += int(item["duration"])

    return {
        "road_id": str(road_id),
        "date": str(data_day),
        "window_start": int(window_start),
        "flow_window_seconds": WINDOW_SECONDS,
        "cycle_observation_start": int(observation_start),
        "cycle_observation_end": int(observation_end),
        "cycle_observation_seconds": (
            int(observation_end) - int(observation_start) + 1
        ),
        "cycle_observation_expanded": bool(observation_expanded),
        "group_id": f"{data_day}:{window_start}:{group_index}",
        "group_size": int(group_size),
        "cycle_index_in_group": int(cycle_index_in_group),
        "pattern": list(cycle["pattern"]),
        "pattern_key": "-".join(cycle["pattern"]),
        "start": cycle["start"],
        "end": cycle["end"],
        "cycle_duration": sum(int(item["duration"]) for item in cycle["items"]),
        "stages": [
            {
                "position": position,
                "stage": str(item["stage"]),
                "duration": int(item["duration"]),
            }
            for position, item in enumerate(cycle["items"])
        ],
        "direction_times": direction_times,
    }


def audit_cleaned_stage_day(stage_map, cross_config, road_id, data_day):
    patterns = normalize_cycle_patterns(cross_config)
    if not patterns:
        raise ValueError(f"Cycle is not configured for road {road_id}")
    layers = compress_stage_layers(stage_map)
    if not layers:
        return [], {"windows_seen": 0, "layers": 0}

    first_window = (layers[0]["start"] // WINDOW_SECONDS) * WINDOW_SECONDS
    last_window = (layers[-1]["end"] // WINDOW_SECONDS) * WINDOW_SECONDS
    samples = []
    stats = Counter(layers=len(layers))
    complete_pattern_counts = Counter()
    consecutive_run_lengths = defaultdict(Counter)
    stats["short_layers_le_3_seconds"] = sum(
        layer["duration"] <= 3 for layer in layers
    )
    phase_map = {
        str(stage): phase_name
        for stage, phase_name in cross_config.get("phase", {}).items()
    }
    for window_start in range(first_window, last_window + 1, WINDOW_SECONDS):
        stats["windows_seen"] += 1
        window_end = window_start + WINDOW_SECONDS - 1
        initial_cycles = find_complete_cycles(
            layers,
            patterns,
            window_start,
            window_end,
        )
        stats["initial_complete_cycles_found"] += len(initial_cycles)
        initial_groups = group_consecutive_same_pattern_cycles(initial_cycles)
        initial_structural_groups = [
            group
            for group in initial_groups
            if len(group) >= MIN_CONSECUTIVE_CYCLES
        ]

        cycles = initial_cycles
        groups = initial_groups
        structural_groups = initial_structural_groups
        observation_start = window_start
        observation_end = window_end
        observation_expanded = False
        expansion_decision = cycle_observation_expansion_decision(
            initial_cycles
        )
        stats[
            f"cycle_observation_decision_{expansion_decision['reason']}"
        ] += 1
        if expansion_decision["should_expand"]:
            observation_start, observation_end = centered_observation_bounds(
                window_start,
                window_end,
            )
            observation_expanded = True
            stats["expanded_observation_attempts"] += 1
            cycles = find_complete_cycles(
                layers,
                patterns,
                observation_start,
                observation_end,
            )
            groups = group_consecutive_same_pattern_cycles(cycles)
            structural_groups = [
                group
                for group in groups
                if len(group) >= MIN_CONSECUTIVE_CYCLES
            ]
            stats["expanded_complete_cycles_found"] += len(cycles)

        stats["complete_cycles_found"] += len(cycles)
        complete_pattern_counts.update(
            "-".join(cycle["pattern"]) for cycle in cycles
        )
        for group in groups:
            pattern_key = "-".join(group[0]["pattern"])
            consecutive_run_lengths[pattern_key][str(len(group))] += 1
        if not structural_groups:
            if observation_expanded:
                stats["expanded_observation_failed"] += 1
            stats["windows_without_three_consecutive_cycles"] += 1
            stats["windows_without_three_consistent_cycles"] += 1
            continue

        eligible_groups = []
        for group in structural_groups:
            segments, stage_change_breaks = split_cycle_group_on_stage_change(
                group
            )
            stats["stage_change_breaks"] += len(stage_change_breaks)
            for segment in segments:
                if len(segment) >= MIN_CONSECUTIVE_CYCLES:
                    eligible_groups.append(segment)
                else:
                    stats["cycles_rejected_by_stage_change"] += len(segment)
        if not eligible_groups:
            if observation_expanded:
                stats["expanded_observation_failed"] += 1
            stats["windows_without_three_consistent_cycles"] += 1
            continue

        stats["windows_eligible"] += 1
        if observation_expanded:
            stats["expanded_observation_eligible_windows"] += 1
        stats["eligible_groups"] += len(eligible_groups)
        pattern_keys = {"-".join(group[0]["pattern"]) for group in eligible_groups}
        stats["windows_with_multiple_eligible_patterns"] += int(
            len(pattern_keys) > 1
        )
        for group_index, group in enumerate(eligible_groups):
            stats["eligible_cycles"] += len(group)
            for cycle_index, cycle in enumerate(group):
                sample = _cycle_sample(
                    cycle,
                    road_id,
                    data_day,
                    window_start,
                    phase_map,
                    group_index,
                    cycle_index,
                    len(group),
                    observation_start,
                    observation_end,
                    observation_expanded,
                )
                sample["cycle_observation_expansion_decision"] = dict(
                    expansion_decision
                )
                stats["stage_durations_le_15"] += sum(
                    stage["duration"] <= 15 for stage in sample["stages"]
                )
                samples.append(sample)
    result_stats = dict(stats)
    result_stats["complete_cycle_pattern_counts"] = dict(sorted(
        complete_pattern_counts.items()
    ))
    result_stats["consecutive_run_length_counts"] = {
        pattern_key: dict(sorted(
            counts.items(),
            key=lambda item: int(item[0]),
        ))
        for pattern_key, counts in sorted(consecutive_run_lengths.items())
    }
    result_stats["stage_layer_counts"] = dict(sorted(Counter(
        layer["stage"] for layer in layers
    ).items()))
    result_stats["stage_layer_seconds"] = dict(sorted(Counter({
        stage: sum(
            layer["duration"] for layer in layers if layer["stage"] == stage
        )
        for stage in {layer["stage"] for layer in layers}
    }).items()))
    result_stats["top_stage_transitions"] = dict(Counter(
        f"{previous['stage']}->{current['stage']}"
        for previous, current in zip(layers, layers[1:])
    ).most_common(20))
    return samples, result_stats


def _nearest_rank(values, quantile):
    if not values:
        return None
    ordered = sorted(int(value) for value in values)
    rank = max(1, math.ceil(float(quantile) * len(ordered)))
    return ordered[rank - 1]


def summarize_duration_values(values):
    ordered = sorted(int(value) for value in values)
    if not ordered:
        return {}
    p05 = _nearest_rank(ordered, 0.05)
    p25 = _nearest_rank(ordered, 0.25)
    p50 = _nearest_rank(ordered, 0.50)
    p75 = _nearest_rank(ordered, 0.75)
    p95 = _nearest_rank(ordered, 0.95)
    median_value = float(median(ordered))
    mad = float(median(abs(value - median_value) for value in ordered))
    iqr = p75 - p25
    mad_tolerance = max(
        MIN_SECONDS_TOLERANCE,
        3 * 1.4826 * mad,
    )
    iqr_lower = max(0.0, p25 - 1.5 * iqr)
    iqr_upper = p75 + 1.5 * iqr
    mad_lower = max(0.0, median_value - mad_tolerance)
    mad_upper = median_value + mad_tolerance
    return {
        "sample_count": len(ordered),
        "min": ordered[0],
        "p05": p05,
        "p25": p25,
        "median": round(median_value, 3),
        "p50": p50,
        "p75": p75,
        "p95": p95,
        "max": ordered[-1],
        "iqr": iqr,
        "mad": round(mad, 3),
        "iqr_candidate_range": [round(iqr_lower, 3), round(iqr_upper, 3)],
        "mad_candidate_range": [round(mad_lower, 3), round(mad_upper, 3)],
        "histogram": {
            str(value): count
            for value, count in sorted(Counter(ordered).items())
        },
    }


def summarize_change_values(values):
    summary = summarize_duration_values(values)
    if summary:
        summary["suggested_max_delta_seconds"] = max(
            MIN_SECONDS_TOLERANCE,
            summary["p95"],
        )
        robust_upper = math.ceil(summary["mad_candidate_range"][1])
        summary["suggested_robust_max_delta_seconds"] = max(
            MIN_SECONDS_TOLERANCE,
            min(summary["p95"], robust_upper),
        )
        summary["suggestion_is_enforced"] = False
    return summary


def summarize_stage_change_values(values):
    summary = summarize_change_values(values)
    if summary:
        summary["configured_max_delta_seconds"] = (
            MAX_ADJACENT_STAGE_CHANGE_SECONDS
        )
        summary["configured_limit_is_enforced_in_cycle_quality"] = True
    return summary


def _adjacent_change_profile(pattern_samples, stage_count):
    groups = defaultdict(list)
    for sample in pattern_samples:
        groups[sample["group_id"]].append(sample)

    cycle_deltas = []
    stage_deltas = [[] for _ in range(stage_count)]
    direction_deltas = {direction: [] for direction in DIRECTIONS}
    cycle_group_ranges = []
    stage_group_ranges = [[] for _ in range(stage_count)]
    direction_group_ranges = {direction: [] for direction in DIRECTIONS}
    for group_samples in groups.values():
        ordered = sorted(
            group_samples,
            key=lambda sample: sample["cycle_index_in_group"],
        )
        cycle_group_ranges.append(
            max(sample["cycle_duration"] for sample in ordered)
            - min(sample["cycle_duration"] for sample in ordered)
        )
        for position in range(stage_count):
            values = [
                sample["stages"][position]["duration"] for sample in ordered
            ]
            stage_group_ranges[position].append(max(values) - min(values))
        for direction in DIRECTIONS:
            values = [sample["direction_times"][direction] for sample in ordered]
            direction_group_ranges[direction].append(max(values) - min(values))
        for previous, current in zip(ordered, ordered[1:]):
            cycle_deltas.append(abs(
                current["cycle_duration"] - previous["cycle_duration"]
            ))
            for position in range(stage_count):
                stage_deltas[position].append(abs(
                    current["stages"][position]["duration"]
                    - previous["stages"][position]["duration"]
                ))
            for direction in DIRECTIONS:
                direction_deltas[direction].append(abs(
                    current["direction_times"][direction]
                    - previous["direction_times"][direction]
                ))

    return {
        "group_count": len(groups),
        "comparison_count": len(cycle_deltas),
        "cycle_duration_absolute_delta": summarize_change_values(cycle_deltas),
        "stages": {
            str(position): summarize_stage_change_values(values)
            for position, values in enumerate(stage_deltas)
        },
        "directions": {
            direction: summarize_change_values(values)
            for direction, values in direction_deltas.items()
        },
        "within_group_ranges": {
            "cycle_duration": summarize_change_values(cycle_group_ranges),
            "stages": {
                str(position): summarize_change_values(values)
                for position, values in enumerate(stage_group_ranges)
            },
            "directions": {
                direction: summarize_change_values(values)
                for direction, values in direction_group_ranges.items()
            },
        },
    }


def build_cycle_profile(samples):
    grouped = defaultdict(list)
    for sample in samples:
        grouped[(sample["road_id"], sample["pattern_key"])].append(sample)

    roads = {}
    for (road_id, pattern_key), pattern_samples in sorted(grouped.items()):
        pattern = pattern_samples[0]["pattern"]
        profile = {
            "pattern": pattern,
            "cycle_count": len(pattern_samples),
            "distinct_dates": sorted({sample["date"] for sample in pattern_samples}),
            "cycle_duration": summarize_duration_values(
                [sample["cycle_duration"] for sample in pattern_samples]
            ),
            "stages": {},
            "directions": {},
            "adjacent_cycle_changes": _adjacent_change_profile(
                pattern_samples,
                len(pattern),
            ),
        }
        for position, stage in enumerate(pattern):
            profile["stages"][str(position)] = {
                "stage": stage,
                "duration": summarize_duration_values([
                    sample["stages"][position]["duration"]
                    for sample in pattern_samples
                ]),
            }
        for direction in DIRECTIONS:
            profile["directions"][direction] = summarize_duration_values([
                sample["direction_times"][direction]
                for sample in pattern_samples
            ])
        roads.setdefault(road_id, {"patterns": {}})["patterns"][pattern_key] = profile

    for road_id, road_data in roads.items():
        road_patterns = road_data["patterns"].values()
        road_data["summary"] = {
            "pattern_count": len(road_data["patterns"]),
            "cycle_count": sum(pattern["cycle_count"] for pattern in road_patterns),
            "distinct_dates": sorted({
                date
                for pattern in road_data["patterns"].values()
                for date in pattern["distinct_dates"]
            }),
        }
    return {
        "mode": "learning_only",
        "flow_window_seconds": WINDOW_SECONDS,
        "cycle_observation_policy": {
            "initial_seconds": WINDOW_SECONDS,
            "expanded_seconds": CYCLE_OBSERVATION_WINDOW_SECONDS,
            "long_cycle_threshold_seconds": LONG_CYCLE_THRESHOLD_SECONDS,
            "duration_statistic": "median_of_initial_complete_cycles",
            "expansion": "centered_when_fewer_than_three_cycles_and_median_over_threshold",
        },
        "minimum_consecutive_cycles": MIN_CONSECUTIVE_CYCLES,
        "stage_consistency_rule": {
            "scope": "adjacent cycles in the same pattern run",
            "max_stage_change_seconds": MAX_ADJACENT_STAGE_CHANGE_SECONDS,
            "action": "split the run at the excessive change",
            "enforced_in_cycle_quality": True,
            "enforced_in_training": True,
        },
        "candidate_ranges_are_enforced": False,
        "roads": roads,
    }


def build_cycle_samples(samples):
    roads = {}
    for sample in samples:
        road_id = sample["road_id"]
        pattern_key = sample["pattern_key"]
        roads.setdefault(road_id, {}).setdefault(pattern_key, []).append(sample)
    return {
        "mode": "learning_only",
        "flow_window_seconds": WINDOW_SECONDS,
        "cycle_observation_window_seconds": CYCLE_OBSERVATION_WINDOW_SECONDS,
        "long_cycle_threshold_seconds": LONG_CYCLE_THRESHOLD_SECONDS,
        "roads": roads,
    }


def run_cycle_quality_analysis(
    dates,
    road_ids,
    project_root,
    output_prefix,
    cross_info_path=None,
):
    dates = [str(value) for value in dates]
    road_ids = {str(value) for value in road_ids}
    if not dates or not road_ids:
        raise ValueError("dates and road_ids are required")
    if cross_info_path is None:
        cross_info_path = os.path.join(project_root, "lib", "cross_info.json")
    with open(cross_info_path, "r", encoding="utf-8") as file:
        cross_info = json.load(file)

    all_samples = []
    run_days = {}
    for data_day in dates:
        extend_path = os.path.join(
            project_root,
            "logs_data",
            "extend",
            f"{data_day}_extend.txt",
        )
        cleaning_report_path = f"{output_prefix}_{data_day}_stage_cleaning.json"
        cleaned, cleaning_report = clean_stage_inputs(
            extend_path,
            cross_info,
            target_cross_ids=road_ids,
            report_path=cleaning_report_path,
        )
        day_roads = {}
        for road_id in sorted(road_ids):
            samples, stats = audit_cleaned_stage_day(
                cleaned.get(road_id, {}),
                cross_info[road_id],
                road_id,
                data_day,
            )
            all_samples.extend(samples)
            day_roads[road_id] = stats
        run_days[data_day] = {
            "cleaning_report": os.path.abspath(cleaning_report_path),
            "stage_coverage": {
                road_id: cleaning_report["crosses"][road_id]["stage_coverage"]
                for road_id in sorted(road_ids)
            },
            "roads": day_roads,
        }

    profile_path = f"{output_prefix}_profile.json"
    samples_path = f"{output_prefix}_samples.json"
    run_report_path = f"{output_prefix}_run_report.json"
    profile = build_cycle_profile(all_samples)
    samples_data = build_cycle_samples(all_samples)
    run_report = {
        "dates": dates,
        "road_ids": sorted(road_ids),
        "profile_output": os.path.abspath(profile_path),
        "samples_output": os.path.abspath(samples_path),
        "candidate_ranges_are_enforced": False,
        "flow_window_seconds": WINDOW_SECONDS,
        "cycle_observation_window_seconds": CYCLE_OBSERVATION_WINDOW_SECONDS,
        "long_cycle_threshold_seconds": LONG_CYCLE_THRESHOLD_SECONDS,
        "adaptive_cycle_observation_enabled": True,
        "stage_consistency_rule": {
            "max_stage_change_seconds": MAX_ADJACENT_STAGE_CHANGE_SECONDS,
            "enforced_in_cycle_quality": True,
            "enforced_in_training": True,
        },
        "days": run_days,
    }
    _write_json_atomic(profile_path, profile)
    _write_json_atomic(samples_path, samples_data)
    _write_json_atomic(run_report_path, run_report)
    return profile, samples_data, run_report


def _build_parser():
    module_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(module_dir, os.pardir, os.pardir))
    parser = argparse.ArgumentParser(description="Learn cycle-duration quality profiles")
    parser.add_argument("--dates", required=True)
    parser.add_argument("--road-ids", required=True)
    parser.add_argument("--project-root", default=project_root)
    parser.add_argument("--cross-info")
    parser.add_argument("--output-prefix", required=True)
    return parser


def main():
    args = _build_parser().parse_args()
    _, _, report = run_cycle_quality_analysis(
        dates=[value.strip() for value in args.dates.split(",") if value.strip()],
        road_ids=[value.strip() for value in args.road_ids.split(",") if value.strip()],
        project_root=os.path.abspath(args.project_root),
        output_prefix=os.path.abspath(args.output_prefix),
        cross_info_path=args.cross_info,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
