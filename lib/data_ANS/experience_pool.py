import argparse
import copy
import json
import math
import os
import tempfile
from collections import Counter


LANE_COUNT = 10
VALID_DIRECTIONS = {"U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL"}
DEFAULT_PERCENTILE = 0.80
DEFAULT_OLD_WEIGHT = 0.80
DEFAULT_NEW_WEIGHT = 0.20
DEFAULT_AUDIT_MIN_SAMPLE_COUNT = 5
DEFAULT_AUDIT_MIN_DATE_SUPPORT = 2
DEFAULT_POOL_MIN_SAMPLE_COUNT = 30
DEFAULT_POOL_SELECTION_METHOD = "densest_cluster_median"
DEFAULT_DENSE_CLUSTER_FRACTION = 0.50
POOL_SELECTION_METHODS = frozenset({"densest_cluster_median", "p80"})


def _sample_capacity_lane_indexes(sample):
    metadata = sample.get("metadata") or {}
    requested = metadata.get("capacity_lane_indexes")
    if requested is None:
        return set(range(LANE_COUNT))
    if not isinstance(requested, (list, tuple, set)):
        raise ValueError("capacity_lane_indexes must be a lane index list")
    indexes = {int(lane) for lane in requested}
    if not indexes or any(lane < 0 or lane >= LANE_COUNT for lane in indexes):
        raise ValueError("capacity_lane_indexes contains an invalid lane")
    return indexes


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


def _load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return copy.deepcopy(default)


def _normalize_flow_vector(flow):
    if not isinstance(flow, (list, tuple)) or len(flow) != LANE_COUNT:
        raise ValueError(f"flow vector must contain exactly {LANE_COUNT} lanes")

    result = []
    for value in flow:
        number = int(value)
        if number < 0:
            raise ValueError("flow values must be non-negative")
        result.append(number)
    return result


def nearest_rank_percentile(values, percentile=DEFAULT_PERCENTILE):
    percentile = float(percentile)
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in the interval (0, 1]")
    if not values:
        return None

    ordered = sorted(int(value) for value in values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _rounded_median(ordered_values):
    count = len(ordered_values)
    if count == 0:
        return None
    middle = count // 2
    if count % 2:
        return int(ordered_values[middle])
    return (int(ordered_values[middle - 1]) + int(ordered_values[middle]) + 1) // 2


def densest_cluster_median(
    values,
    cluster_fraction=DEFAULT_DENSE_CLUSTER_FRACTION,
):
    """Select the median of the narrowest interval covering enough samples.

    The default interval contains half of all observations, so a small group
    of downstream-blocked low values or isolated high values cannot determine
    the selected lane capacity. Ties prefer the interval nearest the full
    sample median, then the higher interval.
    """
    cluster_fraction = float(cluster_fraction)
    if not 0 < cluster_fraction <= 1:
        raise ValueError("cluster_fraction must be in the interval (0, 1]")
    if not values:
        return None, {
            "selection_method": DEFAULT_POOL_SELECTION_METHOD,
            "sample_count": 0,
            "cluster_fraction": cluster_fraction,
            "cluster_size": 0,
            "selected_value": None,
        }

    ordered = sorted(int(value) for value in values)
    sample_count = len(ordered)
    cluster_size = max(1, math.ceil(sample_count * cluster_fraction))
    full_median = _rounded_median(ordered)
    best = None
    for start in range(sample_count - cluster_size + 1):
        cluster = ordered[start:start + cluster_size]
        cluster_median = _rounded_median(cluster)
        lower = cluster[0]
        upper = cluster[-1]
        key = (
            upper - lower,
            abs(cluster_median - full_median),
            -cluster_median,
            start,
        )
        if best is None or key < best[0]:
            best = (key, start, cluster, cluster_median)

    _, start, cluster, selected = best
    lower = cluster[0]
    upper = cluster[-1]
    return int(selected), {
        "selection_method": DEFAULT_POOL_SELECTION_METHOD,
        "sample_count": sample_count,
        "cluster_fraction": cluster_fraction,
        "cluster_size": cluster_size,
        "cluster_support_ratio": round(cluster_size / sample_count, 6),
        "cluster_start_rank": start + 1,
        "cluster_end_rank": start + cluster_size,
        "cluster_lower": int(lower),
        "cluster_upper": int(upper),
        "cluster_width": int(upper - lower),
        "full_sample_min": int(ordered[0]),
        "full_sample_max": int(ordered[-1]),
        "full_sample_median": int(full_median),
        "selected_value": int(selected),
        "outside_cluster_count": sample_count - cluster_size,
    }


def select_pool_lane_value(
    values,
    selection_method=DEFAULT_POOL_SELECTION_METHOD,
    percentile=DEFAULT_PERCENTILE,
    cluster_fraction=DEFAULT_DENSE_CLUSTER_FRACTION,
):
    selection_method = str(selection_method).strip().lower()
    if selection_method not in POOL_SELECTION_METHODS:
        raise ValueError(
            "selection_method must be one of: "
            + ", ".join(sorted(POOL_SELECTION_METHODS))
        )
    if selection_method == "p80":
        selected = nearest_rank_percentile(values, percentile)
        return selected, {
            "selection_method": "p80",
            "sample_count": len(values),
            "percentile": float(percentile),
            "selected_value": selected,
        }
    selected, report = densest_cluster_median(
        values,
        cluster_fraction=cluster_fraction,
    )
    report["p80_reference_percentile"] = float(percentile)
    report["p80_reference_value"] = nearest_rank_percentile(values, percentile)
    return selected, report


def _sample_source_id(sample):
    explicit = sample.get("source_id")
    if explicit not in (None, ""):
        return str(explicit)

    data_day = sample.get("date")
    window_start = sample.get("window_start")
    if data_day is None or window_start is None:
        return None
    return f"{data_day}:{int(window_start)}"


def _candidate_sample_count(candidate_samples):
    total = 0
    for road_data in candidate_samples.get("roads", {}).values():
        for time_map in road_data.get("directions", {}).values():
            for samples in time_map.values():
                total += len(samples)
    return total


def _candidate_lane_keys(candidate_samples):
    """Return lane cells that received evidence in this candidate batch."""
    result = set()
    for road_id, road_data in candidate_samples.get("roads", {}).items():
        for direction, time_map in road_data.get("directions", {}).items():
            for green_time, samples in time_map.items():
                for sample in samples:
                    try:
                        lane_indexes = _sample_capacity_lane_indexes(sample)
                        green_time_int = int(green_time)
                    except (TypeError, ValueError):
                        continue
                    for lane_index in lane_indexes:
                        result.add(
                            (
                                str(road_id),
                                str(direction),
                                str(green_time_int),
                                int(lane_index),
                            )
                        )
    return result


def split_candidate_samples_by_date(candidate_samples):
    """Partition a candidate export so daily EWMA updates remain chronological."""
    result = {}
    for road_id, road_data in candidate_samples.get("roads", {}).items():
        for direction, time_map in road_data.get("directions", {}).items():
            for green_time, samples in time_map.items():
                for sample in samples:
                    data_day = sample.get("date")
                    if data_day in (None, ""):
                        raise ValueError(
                            "every candidate sample needs a date for daily updates"
                        )
                    day_data = result.setdefault(
                        str(data_day),
                        {
                            "scope": "single_training_date",
                            "selection_changed": False,
                            "dates": [str(data_day)],
                            "roads": {},
                        },
                    )
                    day_data["roads"].setdefault(str(road_id), {}).setdefault(
                        "directions",
                        {},
                    ).setdefault(direction, {}).setdefault(
                        str(int(green_time)),
                        [],
                    ).append(copy.deepcopy(sample))
    return result


class ExperiencePool:
    """Persistent lane-level experience pool built from cleaned candidates."""

    def __init__(self, data=None, min_green_time=1, max_green_time=150):
        self.min_green_time = int(min_green_time)
        self.max_green_time = int(max_green_time)
        if self.min_green_time > self.max_green_time:
            raise ValueError("min_green_time cannot exceed max_green_time")

        self._roads = {}
        self._seen_samples = set()
        self._state = {}
        if data:
            self._load_pool_data(data)

    def _load_pool_data(self, data):
        if not isinstance(data, dict):
            raise TypeError("full pool must be a dictionary")
        roads = data.get("roads", data)
        if "roads" in data and isinstance(data.get("state"), dict):
            self._state = copy.deepcopy(data["state"])
        if not isinstance(roads, dict):
            raise TypeError("full pool roads must be a dictionary")

        for road_id, directions in roads.items():
            if not isinstance(directions, dict):
                continue
            for direction, time_map in directions.items():
                if direction not in VALID_DIRECTIONS or not isinstance(time_map, dict):
                    continue
                for green_time, lane_map in time_map.items():
                    green_time_int = int(green_time)
                    if not self.min_green_time <= green_time_int <= self.max_green_time:
                        continue
                    if not isinstance(lane_map, dict):
                        continue
                    for lane, records in lane_map.items():
                        lane_index = int(lane)
                        if not 0 <= lane_index < LANE_COUNT or not isinstance(records, list):
                            continue
                        for record in records:
                            if not isinstance(record, dict):
                                continue
                            normalized = self._normalize_pool_record(record)
                            self._append_lane_record(
                                str(road_id),
                                direction,
                                str(green_time_int),
                                str(lane_index),
                                normalized,
                            )
                            source_id = normalized.get("source_id")
                            if source_id:
                                self._seen_samples.add(
                                    (
                                        str(road_id),
                                        direction,
                                        str(green_time_int),
                                        source_id,
                                    )
                                )

    @staticmethod
    def _normalize_pool_record(record):
        flow = int(record["flow"])
        if flow < 0:
            raise ValueError("pool flow values must be non-negative")
        window_start = record.get("window_start")
        return {
            "flow": flow,
            "date": (
                str(record["date"]) if record.get("date") is not None else None
            ),
            "window_start": (
                int(window_start) if window_start is not None else None
            ),
            "source_id": (
                str(record["source_id"])
                if record.get("source_id") not in (None, "")
                else None
            ),
            "metadata": dict(record.get("metadata") or {}),
        }

    def _append_lane_record(self, road_id, direction, green_time, lane, record):
        self._roads.setdefault(road_id, {}).setdefault(direction, {}).setdefault(
            green_time,
            {},
        ).setdefault(lane, []).append(record)

    def add_candidate_samples(self, candidate_samples):
        if not isinstance(candidate_samples, dict):
            raise TypeError("candidate samples must be a dictionary")
        roads = candidate_samples.get("roads", {})
        stats = Counter()

        for road_id, road_data in roads.items():
            directions = road_data.get("directions", {})
            for direction, time_map in directions.items():
                if direction not in VALID_DIRECTIONS:
                    stats["invalid_direction"] += 1
                    continue
                for green_time, samples in time_map.items():
                    try:
                        green_time_int = int(green_time)
                    except (TypeError, ValueError):
                        stats["invalid_green_time"] += len(samples)
                        continue
                    if not self.min_green_time <= green_time_int <= self.max_green_time:
                        stats["green_time_out_of_range"] += len(samples)
                        continue

                    for sample in samples:
                        try:
                            flow = _normalize_flow_vector(sample["flow"])
                            capacity_lanes = _sample_capacity_lane_indexes(sample)
                        except (KeyError, TypeError, ValueError):
                            stats["invalid_flow_vector"] += 1
                            continue

                        source_id = _sample_source_id(sample)
                        sample_key = (
                            str(road_id),
                            direction,
                            str(green_time_int),
                            source_id,
                        )
                        if source_id is not None and sample_key in self._seen_samples:
                            stats["duplicate_samples"] += 1
                            continue

                        record_base = {
                            "date": (
                                str(sample["date"])
                                if sample.get("date") is not None
                                else None
                            ),
                            "window_start": (
                                int(sample["window_start"])
                                if sample.get("window_start") is not None
                                else None
                            ),
                            "source_id": source_id,
                            "metadata": dict(sample.get("metadata") or {}),
                        }
                        for lane_index, lane_flow in enumerate(flow):
                            if lane_index not in capacity_lanes:
                                continue
                            record = dict(record_base)
                            record["flow"] = lane_flow
                            self._append_lane_record(
                                str(road_id),
                                direction,
                                str(green_time_int),
                                str(lane_index),
                                record,
                            )

                        if source_id is not None:
                            self._seen_samples.add(sample_key)
                        stats["accepted_samples"] += 1
                        stats["lane_records_added"] += len(capacity_lanes)
                        stats["masked_lane_records"] += (
                            LANE_COUNT - len(capacity_lanes)
                        )

        for key in (
            "accepted_samples",
            "duplicate_samples",
            "lane_records_added",
            "invalid_direction",
            "invalid_green_time",
            "green_time_out_of_range",
            "invalid_flow_vector",
            "masked_lane_records",
        ):
            stats.setdefault(key, 0)
        return dict(stats)

    def build_full_pool(self):
        return {
            "version": 2,
            "pool_type": "full_lane_experience",
            "lane_index_semantics": "array index 0..9 is preserved",
            "state": copy.deepcopy(self._state),
            "roads": copy.deepcopy(self._roads),
        }

    def get_rolling_table(self):
        table = self._state.get("rolling_table")
        return copy.deepcopy(table) if isinstance(table, dict) else None

    def set_rolling_table(self, table, last_update_dates=None):
        if not isinstance(table, dict):
            raise TypeError("rolling table must be a dictionary")
        self._state["rolling_table"] = copy.deepcopy(table)
        if last_update_dates is not None:
            self._state["last_update_dates"] = [
                str(value) for value in last_update_dates
            ]

    def get_processed_source_dates(self):
        return {
            str(value)
            for value in self._state.get("processed_source_dates", [])
        }

    def record_daily_run(self, source_date, run_report):
        source_date = str(source_date)
        processed = self.get_processed_source_dates()
        processed.add(source_date)
        self._state["processed_source_dates"] = sorted(processed)
        self._state.setdefault("daily_runs", {})[source_date] = copy.deepcopy(
            run_report
        )

    def compress_eligible_lane_updates(
        self,
        updated_lane_keys,
        percentile=DEFAULT_PERCENTILE,
        min_sample_count=DEFAULT_POOL_MIN_SAMPLE_COUNT,
        selection_method=DEFAULT_POOL_SELECTION_METHOD,
        cluster_fraction=DEFAULT_DENSE_CLUSTER_FRACTION,
    ):
        """Build Table 2 only for lane cells changed by this source day.

        A representative value is calculated from the cumulative pool. A lane
        is emitted only when its cumulative support reaches ``min_sample_count``
        and the current batch added evidence for that exact lane cell.
        """
        percentile = float(percentile)
        selection_method = str(selection_method).strip().lower()
        if selection_method not in POOL_SELECTION_METHODS:
            raise ValueError(
                "selection_method must be one of: "
                + ", ".join(sorted(POOL_SELECTION_METHODS))
            )
        cluster_fraction = float(cluster_fraction)
        if not 0 < cluster_fraction <= 1:
            raise ValueError("cluster_fraction must be in the interval (0, 1]")
        min_sample_count = max(1, int(min_sample_count))
        updated_lane_keys = {
            (str(road), str(direction), str(int(green_time)), int(lane))
            for road, direction, green_time, lane in updated_lane_keys
        }
        table = {}
        lane_masks = {}
        point_reports = {}
        summary = Counter()

        for road_id, direction, green_time, lane_index in sorted(
            updated_lane_keys,
            key=lambda item: (item[0], item[1], int(item[2]), item[3]),
        ):
            records = (
                self._roads.get(road_id, {})
                .get(direction, {})
                .get(green_time, {})
                .get(str(lane_index), [])
            )
            values = [int(record["flow"]) for record in records]
            dates = sorted(
                {
                    str(record["date"])
                    for record in records
                    if record.get("date") not in (None, "")
                }
            )
            lane_report = {
                "sample_count": len(values),
                "distinct_date_count": len(dates),
                "dates": dates,
                "minimum_sample_count": min_sample_count,
                "selection_method": selection_method,
                "selected_value": None,
                "selected_percentile_value": None,
            }
            point_key = f"{road_id}/{direction}/{green_time}/{lane_index}"
            if len(values) < min_sample_count:
                lane_report["decision"] = "insufficient_cumulative_samples"
                summary["insufficient_lane_cells"] += 1
                point_reports[point_key] = lane_report
                continue

            selected, selection_report = select_pool_lane_value(
                values,
                selection_method=selection_method,
                percentile=percentile,
                cluster_fraction=cluster_fraction,
            )
            vector = (
                table.setdefault(road_id, {})
                .setdefault(direction, {})
                .setdefault(green_time, [0] * LANE_COUNT)
            )
            vector[lane_index] = int(selected)
            mask = (
                lane_masks.setdefault(road_id, {})
                .setdefault(direction, {})
                .setdefault(green_time, [])
            )
            mask.append(lane_index)
            lane_report.update(
                {
                    "decision": (
                        "eligible_cumulative_p80"
                        if selection_method == "p80"
                        else "eligible_cumulative_densest_cluster"
                    ),
                    "selected_value": int(selected),
                    "selected_percentile_value": (
                        int(selected) if selection_method == "p80" else None
                    ),
                    "selection_details": selection_report,
                }
            )
            point_reports[point_key] = lane_report
            summary["eligible_lane_cells"] += 1

        for road_data in lane_masks.values():
            for direction_data in road_data.values():
                for green_time in direction_data:
                    direction_data[green_time] = sorted(
                        set(direction_data[green_time])
                    )

        report = {
            "selection": (
                "cumulative_near_capacity_lane_p80"
                if selection_method == "p80"
                else "cumulative_near_capacity_lane_densest_cluster_median"
            ),
            "selection_method": selection_method,
            "percentile": percentile if selection_method == "p80" else None,
            "cluster_fraction": cluster_fraction,
            "minimum_sample_count": min_sample_count,
            "updated_lane_cell_count": len(updated_lane_keys),
            "summary": dict(summary),
            "lane_cells": point_reports,
        }
        return table, lane_masks, report

    def compress(self, percentile=DEFAULT_PERCENTILE, low_support_threshold=3):
        percentile = float(percentile)
        low_support_threshold = max(1, int(low_support_threshold))
        table = {}
        report_roads = {}

        for road_id in sorted(self._roads):
            table[road_id] = {}
            road_report = {"directions": {}}
            road_summary = Counter()
            for direction in sorted(self._roads[road_id]):
                table[road_id][direction] = {}
                direction_report = {}
                for green_time in sorted(
                    self._roads[road_id][direction],
                    key=int,
                ):
                    lane_map = self._roads[road_id][direction][green_time]
                    vector = [0] * LANE_COUNT
                    lane_report = {}
                    source_ids = set()
                    dates = set()
                    for lane_index in range(LANE_COUNT):
                        records = lane_map.get(str(lane_index), [])
                        values = [int(record["flow"]) for record in records]
                        selected = nearest_rank_percentile(values, percentile)
                        if selected is not None:
                            vector[lane_index] = selected
                        source_ids.update(
                            record["source_id"]
                            for record in records
                            if record.get("source_id")
                        )
                        dates.update(
                            record["date"]
                            for record in records
                            if record.get("date")
                        )
                        lane_report[str(lane_index)] = {
                            "sample_count": len(values),
                            "min": min(values) if values else None,
                            "max": max(values) if values else None,
                            "selected_percentile_value": selected,
                        }

                    sample_count = len(source_ids)
                    if not source_ids:
                        sample_count = max(
                            (
                                len(records)
                                for records in lane_map.values()
                            ),
                            default=0,
                        )
                    flags = []
                    if sample_count < low_support_threshold:
                        flags.append("low_support")
                    table[road_id][direction][green_time] = vector
                    direction_report[green_time] = {
                        "sample_count": sample_count,
                        "distinct_date_count": len(dates),
                        "lanes": lane_report,
                        "flags": flags,
                    }
                    road_summary["experience_points"] += 1
                    road_summary["candidate_samples"] += sample_count
                    road_summary["low_support_points"] += int(bool(flags))

                road_report["directions"][direction] = direction_report
            road_report["summary"] = dict(road_summary)
            report_roads[road_id] = road_report

        report = {
            "selection": "nearest_rank_percentile_per_lane",
            "percentile": percentile,
            "low_support_threshold": low_support_threshold,
            "roads": report_roads,
        }
        return table, report


def select_audit_gated_table(
    candidate_samples,
    audit_report,
    percentile=DEFAULT_PERCENTILE,
    min_sample_count=DEFAULT_AUDIT_MIN_SAMPLE_COUNT,
    min_date_support=DEFAULT_AUDIT_MIN_DATE_SUPPORT,
):
    """Select lane-level P80 points only when the audit has enough support."""
    if not isinstance(candidate_samples, dict):
        raise TypeError("candidate samples must be a dictionary")
    if not isinstance(audit_report, dict):
        raise TypeError("audit report must be a dictionary")

    percentile = float(percentile)
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in the interval (0, 1]")
    min_sample_count = max(1, int(min_sample_count))
    min_date_support = max(1, int(min_date_support))

    table = {}
    report_roads = {}
    summary = Counter()
    candidate_roads = candidate_samples.get("roads", {})
    audit_roads = audit_report.get("roads", {})

    for road_id in sorted(candidate_roads):
        road_samples = candidate_roads.get(road_id, {})
        directions = road_samples.get("directions", {})
        audit_directions = audit_roads.get(road_id, {}).get(
            "directions",
            {},
        )
        selected_directions = {}
        direction_reports = {}
        road_summary = Counter()

        for direction in sorted(directions):
            time_map = directions.get(direction, {})
            audit_time_map = audit_directions.get(direction, {})
            selected_times = {}
            point_reports = {}

            for green_time in sorted(time_map, key=int):
                samples = time_map.get(green_time, [])
                summary["candidate_points"] += 1
                road_summary["candidate_points"] += 1
                audit_point = audit_time_map.get(str(green_time))
                point_report = {
                    "sample_count": len(samples),
                    "audit_flags": [],
                }

                try:
                    green_time_int = int(green_time)
                except (TypeError, ValueError):
                    point_report["decision"] = "rejected_invalid_green_time"
                    summary["rejected_invalid_green_time"] += 1
                    road_summary["rejected_invalid_green_time"] += 1
                    point_reports[str(green_time)] = point_report
                    continue

                if direction not in VALID_DIRECTIONS:
                    point_report["decision"] = "rejected_invalid_direction"
                    summary["rejected_invalid_direction"] += 1
                    road_summary["rejected_invalid_direction"] += 1
                    point_reports[str(green_time_int)] = point_report
                    continue
                if not 1 <= green_time_int <= 150:
                    point_report["decision"] = "rejected_green_time_out_of_range"
                    summary["rejected_green_time_out_of_range"] += 1
                    road_summary["rejected_green_time_out_of_range"] += 1
                    point_reports[str(green_time_int)] = point_report
                    continue
                if not isinstance(audit_point, dict):
                    point_report["decision"] = "rejected_missing_audit"
                    summary["rejected_missing_audit"] += 1
                    road_summary["rejected_missing_audit"] += 1
                    point_reports[str(green_time_int)] = point_report
                    continue

                audit_sample_count = int(audit_point.get("sample_count", -1))
                audit_dates = set(audit_point.get("dates", []))
                audit_flags = list(audit_point.get("flags", []))
                point_report.update(
                    {
                        "audit_sample_count": audit_sample_count,
                        "audit_distinct_date_count": len(audit_dates),
                        "audit_flags": audit_flags,
                    }
                )
                if audit_sample_count != len(samples):
                    point_report["decision"] = "rejected_audit_sample_mismatch"
                    summary["rejected_audit_sample_mismatch"] += 1
                    road_summary["rejected_audit_sample_mismatch"] += 1
                    point_reports[str(green_time_int)] = point_report
                    continue

                flows = []
                flow_lane_masks = []
                dates = set()
                try:
                    for sample in samples:
                        flows.append(_normalize_flow_vector(sample["flow"]))
                        flow_lane_masks.append(_sample_capacity_lane_indexes(sample))
                        if sample.get("date") not in (None, ""):
                            dates.add(str(sample["date"]))
                except (KeyError, TypeError, ValueError):
                    point_report["decision"] = "rejected_invalid_candidate_flow"
                    summary["rejected_invalid_candidate_flow"] += 1
                    road_summary["rejected_invalid_candidate_flow"] += 1
                    point_reports[str(green_time_int)] = point_report
                    continue

                point_report["distinct_date_count"] = len(dates)
                if len(flows) < min_sample_count:
                    point_report["decision"] = "rejected_insufficient_samples"
                    summary["rejected_insufficient_samples"] += 1
                    road_summary["rejected_insufficient_samples"] += 1
                    point_reports[str(green_time_int)] = point_report
                    continue
                if len(dates) < min_date_support:
                    point_report["decision"] = "rejected_insufficient_date_support"
                    summary["rejected_insufficient_date_support"] += 1
                    road_summary["rejected_insufficient_date_support"] += 1
                    point_reports[str(green_time_int)] = point_report
                    continue

                selected_vector = [
                    (
                        nearest_rank_percentile(
                            [
                                flow[lane_index]
                                for flow, lane_mask in zip(flows, flow_lane_masks)
                                if lane_index in lane_mask
                            ],
                            percentile,
                        )
                        or 0
                    )
                    for lane_index in range(LANE_COUNT)
                ]
                outlier_flags = {
                    "isolated_dominant_max",
                    "iqr_high_outlier",
                }
                point_report["decision"] = (
                    "accepted_p80_replacing_isolated_outlier"
                    if outlier_flags.issubset(set(audit_flags))
                    else "accepted_p80"
                )
                point_report["selected_total"] = sum(selected_vector)
                selected_times[str(green_time_int)] = selected_vector
                summary["accepted_points"] += 1
                summary["accepted_candidate_samples"] += len(flows)
                road_summary["accepted_points"] += 1
                road_summary["accepted_candidate_samples"] += len(flows)
                if point_report["decision"] != "accepted_p80":
                    summary["outlier_adjusted_points"] += 1
                    road_summary["outlier_adjusted_points"] += 1
                point_reports[str(green_time_int)] = point_report

            if selected_times:
                selected_directions[direction] = selected_times
            direction_reports[direction] = point_reports

        if selected_directions:
            table[str(road_id)] = selected_directions
        report_roads[str(road_id)] = {
            "summary": dict(road_summary),
            "directions": direction_reports,
        }

    report = {
        "selection": "audit_gated_nearest_rank_percentile_per_lane",
        "selection_changed": True,
        "policy": {
            "percentile": percentile,
            "min_sample_count": min_sample_count,
            "min_date_support": min_date_support,
            "outlier_handling": (
                "P80 replaces points flagged both isolated_dominant_max "
                "and iqr_high_outlier"
            ),
            "insufficient_support_handling": (
                "point omitted for buqi to fill from trusted neighbors"
            ),
        },
        "summary": dict(summary),
        "roads": report_roads,
    }
    return table, report


def run_audit_gated_selection(
    candidate_samples_path,
    audit_path,
    output_path,
    report_path=None,
    percentile=DEFAULT_PERCENTILE,
    min_sample_count=DEFAULT_AUDIT_MIN_SAMPLE_COUNT,
    min_date_support=DEFAULT_AUDIT_MIN_DATE_SUPPORT,
):
    candidate_samples = _load_json(candidate_samples_path)
    audit_report = _load_json(audit_path)
    if not candidate_samples:
        raise ValueError(f"candidate samples are empty: {candidate_samples_path}")
    if not audit_report:
        raise ValueError(f"audit report is empty: {audit_path}")

    table, report = select_audit_gated_table(
        candidate_samples,
        audit_report,
        percentile=percentile,
        min_sample_count=min_sample_count,
        min_date_support=min_date_support,
    )
    if report_path is None:
        report_path = os.path.splitext(output_path)[0] + "_selection_report.json"
    report.update(
        {
            "candidate_samples_path": os.path.abspath(candidate_samples_path),
            "audit_path": os.path.abspath(audit_path),
            "output_path": os.path.abspath(output_path),
        }
    )
    _write_json_atomic(output_path, table)
    _write_json_atomic(report_path, report)
    return table, report


def blend_experience_tables(
    old_table,
    new_table,
    old_weight=DEFAULT_OLD_WEIGHT,
    new_weight=DEFAULT_NEW_WEIGHT,
):
    old_weight = float(old_weight)
    new_weight = float(new_weight)
    if old_weight < 0 or new_weight < 0:
        raise ValueError("blend weights must be non-negative")
    if not math.isclose(old_weight + new_weight, 1.0, abs_tol=1e-9):
        raise ValueError("blend weights must sum to 1.0")

    old_table = old_table or {}
    new_table = new_table or {}
    result = {}
    stats = Counter()

    for road_id in sorted(set(old_table) | set(new_table)):
        result[road_id] = {}
        old_directions = old_table.get(road_id, {})
        new_directions = new_table.get(road_id, {})
        for direction in sorted(set(old_directions) | set(new_directions)):
            result[road_id][direction] = {}
            old_times = old_directions.get(direction, {})
            new_times = new_directions.get(direction, {})
            all_times = sorted(set(old_times) | set(new_times), key=int)
            for green_time in all_times:
                old_flow = old_times.get(green_time)
                new_flow = new_times.get(green_time)
                if old_flow is None:
                    result[road_id][direction][str(green_time)] = _normalize_flow_vector(
                        new_flow
                    )
                    stats["new_points_added"] += 1
                    continue
                if new_flow is None:
                    result[road_id][direction][str(green_time)] = _normalize_flow_vector(
                        old_flow
                    )
                    stats["old_points_preserved"] += 1
                    continue

                old_vector = _normalize_flow_vector(old_flow)
                new_vector = _normalize_flow_vector(new_flow)
                result[road_id][direction][str(green_time)] = [
                    int(math.floor(old_value * old_weight + new_value * new_weight + 0.5))
                    for old_value, new_value in zip(old_vector, new_vector)
                ]
                stats["points_blended"] += 1

    return result, {
        "old_weight": old_weight,
        "new_weight": new_weight,
        **dict(stats),
    }


def blend_eligible_lane_updates(
    old_table,
    p80_table,
    eligible_lane_masks,
    old_weight=DEFAULT_OLD_WEIGHT,
    new_weight=DEFAULT_NEW_WEIGHT,
):
    """Blend only explicitly eligible lane cells into an existing table.

    Missing roads, directions, time points, and lanes never become zero and are
    never created implicitly. The bootstrap table remains the complete shape.
    """
    old_weight = float(old_weight)
    new_weight = float(new_weight)
    if old_weight < 0 or new_weight < 0:
        raise ValueError("blend weights must be non-negative")
    if not math.isclose(old_weight + new_weight, 1.0, abs_tol=1e-9):
        raise ValueError("blend weights must sum to 1.0")

    result = copy.deepcopy(old_table or {})
    stats = Counter()
    changed_points = set()
    for road_id, road_data in eligible_lane_masks.items():
        for direction, direction_data in road_data.items():
            for green_time, lane_indexes in direction_data.items():
                old_flow = (
                    result.get(road_id, {})
                    .get(direction, {})
                    .get(str(green_time))
                )
                new_flow = (
                    p80_table.get(road_id, {})
                    .get(direction, {})
                    .get(str(green_time))
                )
                if old_flow is None or new_flow is None:
                    stats["missing_old_or_p80_points"] += 1
                    stats["lane_values_preserved"] += len(lane_indexes)
                    continue

                old_vector = _normalize_flow_vector(old_flow)
                p80_vector = _normalize_flow_vector(new_flow)
                blended_vector = list(old_vector)
                for lane_index in sorted({int(value) for value in lane_indexes}):
                    if not 0 <= lane_index < LANE_COUNT:
                        raise ValueError("eligible lane mask contains an invalid lane")
                    blended = int(
                        math.floor(
                            old_vector[lane_index] * old_weight
                            + p80_vector[lane_index] * new_weight
                            + 0.5
                        )
                    )
                    stats["lane_values_blended"] += 1
                    if blended != old_vector[lane_index]:
                        blended_vector[lane_index] = blended
                        stats["lane_values_changed"] += 1
                        changed_points.add((road_id, direction, str(green_time)))
                    else:
                        stats["lane_values_unchanged_after_rounding"] += 1
                result[road_id][direction][str(green_time)] = blended_vector

    stats["points_changed"] = len(changed_points)
    return result, {
        "old_weight": old_weight,
        "new_weight": new_weight,
        "changed_points": [
            "/".join(item)
            for item in sorted(
                changed_points,
                key=lambda value: (value[0], value[1], int(value[2])),
            )
        ],
        **dict(stats),
    }


def run_daily_pool_update(
    candidate_samples_path,
    full_pool_path,
    old_table_path,
    output_path,
    report_path=None,
    percentile=DEFAULT_PERCENTILE,
    old_weight=DEFAULT_OLD_WEIGHT,
    new_weight=DEFAULT_NEW_WEIGHT,
    min_sample_count=DEFAULT_POOL_MIN_SAMPLE_COUNT,
    update_road_ids=None,
    authoritative_old_table=False,
    selection_method=DEFAULT_POOL_SELECTION_METHOD,
    cluster_fraction=DEFAULT_DENSE_CLUSTER_FRACTION,
):
    candidate_samples = _load_json(candidate_samples_path)
    if not candidate_samples:
        raise ValueError(f"candidate samples are empty: {candidate_samples_path}")

    existing_pool = _load_json(full_pool_path, default={})
    full_pool = ExperiencePool(existing_pool)
    candidates_by_date = split_candidate_samples_by_date(candidate_samples)
    if not candidates_by_date:
        raise ValueError("candidate samples contain no dated records")

    update_road_ids = (
        None
        if update_road_ids is None
        else {str(road_id) for road_id in update_road_ids}
    )

    state_table = full_pool.get_rolling_table()
    if authoritative_old_table:
        current_table = _load_json(old_table_path, default={})
        effective_old_table_path = old_table_path
    elif state_table is not None:
        current_table = state_table
        effective_old_table_path = f"{full_pool_path}#state.rolling_table"
    elif os.path.exists(output_path):
        current_table = _load_json(output_path, default={})
        effective_old_table_path = output_path
    else:
        current_table = _load_json(old_table_path, default={})
        effective_old_table_path = old_table_path

    daily_reports = {}
    total_accumulation = Counter()
    total_blend = Counter()
    processed_source_dates = full_pool.get_processed_source_dates()
    for data_day in sorted(candidates_by_date):
        daily_candidates = candidates_by_date[data_day]
        if data_day in processed_source_dates:
            daily_reports[data_day] = {
                "status": "already_applied",
                "expected_samples": _candidate_sample_count(daily_candidates),
            }
            continue

        expected_samples = _candidate_sample_count(daily_candidates)
        accumulation_stats = full_pool.add_candidate_samples(daily_candidates)
        total_accumulation.update(accumulation_stats)
        accepted_samples = int(accumulation_stats.get("accepted_samples", 0))

        if accepted_samples == 0:
            raise ValueError(
                f"candidate date was not marked processed but all samples are "
                f"duplicates: date={data_day}"
            )
        if accepted_samples != expected_samples:
            raise ValueError(
                f"partial duplicate candidate day is unsafe to blend: "
                f"date={data_day}, expected={expected_samples}, "
                f"accepted={accepted_samples}"
            )

        all_updated_lane_keys = _candidate_lane_keys(daily_candidates)
        updated_lane_keys = {
            lane_key
            for lane_key in all_updated_lane_keys
            if update_road_ids is None or lane_key[0] in update_road_ids
        }
        selected_table, eligible_lane_masks, compression_report = (
            full_pool.compress_eligible_lane_updates(
                updated_lane_keys=updated_lane_keys,
                percentile=percentile,
                min_sample_count=min_sample_count,
                selection_method=selection_method,
                cluster_fraction=cluster_fraction,
            )
        )
        current_table, blend_report = blend_eligible_lane_updates(
            current_table,
            selected_table,
            eligible_lane_masks,
            old_weight=old_weight,
            new_weight=new_weight,
        )
        total_blend.update(
            {
                key: value
                for key, value in blend_report.items()
                if key not in {"old_weight", "new_weight"}
            }
        )
        eligible_count = int(
            compression_report.get("summary", {}).get(
                "eligible_lane_cells",
                0,
            )
        )
        changed_count = int(blend_report.get("lane_values_changed", 0))
        if eligible_count == 0:
            status = "pool_updated_threshold_not_met"
        elif changed_count == 0:
            status = "pool_updated_no_table_change"
        else:
            status = "pool_updated_table_updated"
        daily_report = {
            "status": status,
            "expected_samples": expected_samples,
            "candidate_lane_cells": len(all_updated_lane_keys),
            "update_allowed_lane_cells": len(updated_lane_keys),
            "update_withheld_lane_cells": (
                len(all_updated_lane_keys) - len(updated_lane_keys)
            ),
            "accumulation": accumulation_stats,
            "compression": compression_report,
            "blend": blend_report,
        }
        daily_reports[data_day] = daily_report
        full_pool.record_daily_run(data_day, daily_report)
        processed_source_dates.add(data_day)

    full_pool.set_rolling_table(
        current_table,
        last_update_dates=sorted(candidates_by_date),
    )
    _write_json_atomic(full_pool_path, full_pool.build_full_pool())
    _write_json_atomic(output_path, current_table)

    if report_path is None:
        report_path = os.path.splitext(output_path)[0] + "_pool_report.json"
    report = {
        "candidate_samples_path": os.path.abspath(candidate_samples_path),
        "full_pool_path": os.path.abspath(full_pool_path),
        "old_table_path": os.path.abspath(old_table_path),
        "effective_old_table_path": os.path.abspath(effective_old_table_path),
        "output_path": os.path.abspath(output_path),
        "percentile": (
            float(percentile) if selection_method == "p80" else None
        ),
        "old_weight": float(old_weight),
        "new_weight": float(new_weight),
        "minimum_sample_count": int(min_sample_count),
        "selection_method": str(selection_method),
        "cluster_fraction": float(cluster_fraction),
        "update_road_ids": (
            None if update_road_ids is None else sorted(update_road_ids)
        ),
        "authoritative_old_table": bool(authoritative_old_table),
        "accumulation": dict(total_accumulation),
        "blend": dict(total_blend),
        "days": daily_reports,
    }
    _write_json_atomic(report_path, report)
    return current_table, report


def _build_parser():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    lib_dir = os.path.abspath(os.path.join(base_dir, os.pardir))
    pool_dir = os.path.join(lib_dir, "experience_pool")
    parser = argparse.ArgumentParser(description="Update the lane experience pool")
    parser.add_argument("--candidates", required=True)
    parser.add_argument(
        "--full-pool",
        default=os.path.join(pool_dir, "experience_pool_full.json"),
    )
    parser.add_argument(
        "--old-table",
        default=os.path.join(pool_dir, "new_wwx.json"),
    )
    parser.add_argument(
        "--output",
        default=os.path.join(pool_dir, "experience_pool_table.json"),
    )
    parser.add_argument("--report")
    parser.add_argument("--percentile", type=float, default=DEFAULT_PERCENTILE)
    parser.add_argument("--old-weight", type=float, default=DEFAULT_OLD_WEIGHT)
    parser.add_argument("--new-weight", type=float, default=DEFAULT_NEW_WEIGHT)
    parser.add_argument("--audit")
    parser.add_argument("--robust-output")
    parser.add_argument("--robust-report")
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_AUDIT_MIN_SAMPLE_COUNT,
    )
    parser.add_argument(
        "--min-date-support",
        type=int,
        default=DEFAULT_AUDIT_MIN_DATE_SUPPORT,
    )
    parser.add_argument(
        "--pool-min-samples",
        type=int,
        default=DEFAULT_POOL_MIN_SAMPLE_COUNT,
    )
    parser.add_argument(
        "--pool-selection",
        choices=sorted(POOL_SELECTION_METHODS),
        default=DEFAULT_POOL_SELECTION_METHOD,
    )
    parser.add_argument(
        "--cluster-fraction",
        type=float,
        default=DEFAULT_DENSE_CLUSTER_FRACTION,
    )
    parser.add_argument(
        "--update-road",
        action="append",
        help="Only blend these road IDs; all candidate roads are still stored",
    )
    return parser


def main():
    args = _build_parser().parse_args()
    if args.audit or args.robust_output or args.robust_report:
        if not args.audit or not args.robust_output:
            raise SystemExit(
                "--audit and --robust-output must be used together"
            )
        _, report = run_audit_gated_selection(
            candidate_samples_path=args.candidates,
            audit_path=args.audit,
            output_path=args.robust_output,
            report_path=args.robust_report,
            percentile=args.percentile,
            min_sample_count=args.min_samples,
            min_date_support=args.min_date_support,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    _, report = run_daily_pool_update(
        candidate_samples_path=args.candidates,
        full_pool_path=args.full_pool,
        old_table_path=args.old_table,
        output_path=args.output,
        report_path=args.report,
        percentile=args.percentile,
        old_weight=args.old_weight,
        new_weight=args.new_weight,
        min_sample_count=args.pool_min_samples,
        update_road_ids=args.update_road,
        selection_method=args.pool_selection,
        cluster_fraction=args.cluster_fraction,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
