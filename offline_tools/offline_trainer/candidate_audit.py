"""独立离线训练模块 - 候选经验样本审计与去噪 (Candidate Audit).

完全独立，零外部依赖，仅基于 Python 标准库。
"""

from __future__ import annotations

import math
from collections import Counter
from statistics import median, pstdev

DEFAULT_LOW_SUPPORT_THRESHOLD = 3
DEFAULT_DOMINANT_MAX_RATIO = 1.5
DEFAULT_DOMINANT_MAX_MIN_GAP = 5
DEFAULT_MIN_DATE_SUPPORT = 2
DEFAULT_IQR_OUTLIER_MULTIPLIER = 1.5
LANE_COUNT = 10


def _normalize_flow_vector(flow):
    if not isinstance(flow, (list, tuple)):
        raise TypeError("flow vector must be a list or tuple")

    result = []
    for value in flow:
        number = int(value)
        if number < 0:
            raise ValueError("flow values must be non-negative")
        result.append(number)
    return result


def _nearest_rank(values, quantile):
    if not values:
        return None
    rank = max(1, math.ceil(float(quantile) * len(values)))
    return values[rank - 1]


class ExperienceCandidateAudit:
    """在选取代表值之前收集样本置信度、样本量与离群度指标。"""

    def __init__(
        self,
        low_support_threshold=DEFAULT_LOW_SUPPORT_THRESHOLD,
        dominant_max_ratio=DEFAULT_DOMINANT_MAX_RATIO,
        dominant_max_min_gap=DEFAULT_DOMINANT_MAX_MIN_GAP,
        min_date_support=DEFAULT_MIN_DATE_SUPPORT,
        iqr_outlier_multiplier=DEFAULT_IQR_OUTLIER_MULTIPLIER,
    ):
        self.low_support_threshold = max(1, int(low_support_threshold))
        self.dominant_max_ratio = max(1.0, float(dominant_max_ratio))
        self.dominant_max_min_gap = max(0, int(dominant_max_min_gap))
        self.min_date_support = max(1, int(min_date_support))
        self.iqr_outlier_multiplier = max(0.0, float(iqr_outlier_multiplier))
        self._points = {}

    def add_experience(
        self,
        road_id,
        experience,
        *,
        data_day=None,
        window_start=None,
        metadata=None,
    ):
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary")
        metadata = dict(metadata or {})
        capacity_lane_indexes = metadata.get("capacity_lane_indexes")
        if capacity_lane_indexes is not None:
            if not isinstance(capacity_lane_indexes, (list, tuple, set)):
                raise ValueError("capacity_lane_indexes must be a lane index list")
            try:
                capacity_lane_indexes = {
                    int(lane) for lane in capacity_lane_indexes
                }
            except (TypeError, ValueError):
                raise ValueError("capacity_lane_indexes must contain integers")
            if not capacity_lane_indexes or any(
                lane < 0 or lane >= LANE_COUNT
                for lane in capacity_lane_indexes
            ):
                raise ValueError("capacity_lane_indexes contains an invalid lane")
            metadata["capacity_lane_indexes"] = sorted(capacity_lane_indexes)

        road_id = str(road_id)
        road_points = self._points.setdefault(road_id, {})

        for direction, time_map in experience.items():
            if not isinstance(time_map, dict):
                raise TypeError("direction experience must be a dictionary")

            direction = str(direction)
            direction_points = road_points.setdefault(direction, {})
            for green_time, flow in time_map.items():
                time_key = str(int(green_time))
                vector = _normalize_flow_vector(flow)
                if capacity_lane_indexes is not None:
                    vector = [
                        value if index in capacity_lane_indexes else 0
                        for index, value in enumerate(vector)
                    ]
                total = sum(vector)
                point = direction_points.setdefault(
                    time_key,
                    {
                        "samples": [],
                        "totals": [],
                        "dates": Counter(),
                        "windows": [],
                        "metadata": [],
                    },
                )
                point["samples"].append(vector)
                point["totals"].append(total)
                if data_day is not None:
                    point["dates"][str(data_day)] += 1
                if window_start is not None:
                    point["windows"].append(int(window_start))
                point["metadata"].append(metadata)

    def audit_point(self, road_id, direction, green_time):
        road_points = self._points.get(str(road_id), {})
        direction_points = road_points.get(str(direction), {})
        point = direction_points.get(str(int(green_time)))
        if not point or not point["samples"]:
            return {
                "sample_count": 0,
                "distinct_date_count": 0,
                "max_total": None,
                "flags": ["no_samples"],
            }

        totals = sorted(point["totals"])
        sample_count = len(totals)
        dates = sorted(point["dates"].keys())
        distinct_date_count = len(dates)
        max_total = totals[-1]
        second_max_total = totals[-2] if sample_count > 1 else totals[0]
        min_total = totals[0]
        q1 = _nearest_rank(totals, 0.25)
        med = median(totals)
        q3 = _nearest_rank(totals, 0.75)
        p80 = _nearest_rank(totals, 0.80)
        p90 = _nearest_rank(totals, 0.90)
        iqr = q3 - q1
        std_dev = pstdev(totals) if sample_count > 1 else 0.0

        iqr_upper_threshold = (
            q3 + self.iqr_outlier_multiplier * iqr
            if self.iqr_outlier_multiplier > 0
            else None
        )
        iqr_outliers = (
            [value for value in totals if value > iqr_upper_threshold]
            if iqr_upper_threshold is not None
            else []
        )

        flags = []
        if sample_count < self.low_support_threshold:
            flags.append("low_support")
        if distinct_date_count < self.min_date_support:
            flags.append("single_date_support")
        dominant_by_ratio = (
            second_max_total > 0
            and max_total / second_max_total >= self.dominant_max_ratio
        )
        dominant_by_gap = (
            max_total - second_max_total >= self.dominant_max_min_gap
        )
        if (
            sample_count > 1
            and (dominant_by_ratio or dominant_by_gap)
            and max_total > min_total
        ):
            flags.append("dominant_max")
        if iqr_outliers:
            flags.append("iqr_outlier")

        lane_samples = [
            [sample[lane] for sample in point["samples"]]
            for lane in range(LANE_COUNT)
        ]
        lanes = []
        for lane_values in lane_samples:
            ordered = sorted(lane_values)
            lanes.append({
                "max": ordered[-1],
                "median": median(ordered),
                "p80": _nearest_rank(ordered, 0.80),
                "p90": _nearest_rank(ordered, 0.90),
            })

        return {
            "sample_count": sample_count,
            "distinct_date_count": distinct_date_count,
            "dates": dates,
            "min_total": min_total,
            "max_total": max_total,
            "second_max_total": second_max_total,
            "median_total": med,
            "p80_total": p80,
            "p90_total": p90,
            "q1_total": q1,
            "q3_total": q3,
            "iqr_total": iqr,
            "std_dev_total": round(std_dev, 4),
            "iqr_upper_threshold": (
                round(iqr_upper_threshold, 4)
                if iqr_upper_threshold is not None
                else None
            ),
            "outlier_count": len(iqr_outliers),
            "flags": flags,
            "lanes": lanes,
        }

    def build_report(self):
        roads = {}
        totals = Counter()

        for road_id in sorted(self._points):
            directions = {}
            road_summary = Counter()
            for direction in sorted(self._points[road_id]):
                time_map = {}
                for green_time in sorted(
                    self._points[road_id][direction],
                    key=int,
                ):
                    audit = self.audit_point(road_id, direction, green_time)
                    time_map[green_time] = audit
                    totals["points"] += 1
                    road_summary["points"] += 1
                    for flag in audit["flags"]:
                        totals[flag] += 1
                        road_summary[flag] += 1
                directions[direction] = time_map

            roads[road_id] = {
                "summary": dict(road_summary),
                "directions": directions,
            }

        return {
            "summary": dict(totals),
            "thresholds": {
                "low_support_threshold": self.low_support_threshold,
                "dominant_max_ratio": self.dominant_max_ratio,
                "dominant_max_min_gap": self.dominant_max_min_gap,
                "min_date_support": self.min_date_support,
                "iqr_outlier_multiplier": self.iqr_outlier_multiplier,
            },
            "roads": roads,
        }

    def build_samples(self):
        roads = {}
        totals = Counter()
        for road_id in sorted(self._points):
            directions = {}
            road_totals = Counter()
            for direction in sorted(self._points[road_id]):
                time_map = {}
                for green_time in sorted(
                    self._points[road_id][direction],
                    key=int,
                ):
                    raw_point = self._points[road_id][direction][green_time]
                    samples = []
                    for index, flow in enumerate(raw_point["samples"]):
                        date_key = (
                            list(raw_point["dates"])[0]
                            if len(raw_point["dates"]) == 1
                            else None
                        )
                        window_start = (
                            raw_point["windows"][index]
                            if index < len(raw_point["windows"])
                            else None
                        )
                        meta = (
                            raw_point["metadata"][index]
                            if index < len(raw_point["metadata"])
                            else {}
                        )
                        samples.append({
                            "flow": flow,
                            "date": date_key,
                            "window_start": window_start,
                            "metadata": meta,
                        })
                    time_map[green_time] = samples
                    road_totals["points"] += 1
                    road_totals["samples"] += len(samples)
                    totals["points"] += 1
                    totals["samples"] += len(samples)
                directions[direction] = time_map
            roads[road_id] = {
                "summary": dict(road_totals),
                "directions": directions,
            }
        return {
            "summary": dict(totals),
            "roads": roads,
        }
