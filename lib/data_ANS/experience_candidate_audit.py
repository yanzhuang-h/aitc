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
    """Collect evidence about candidates before a robust-max rule is chosen."""

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
                        "sample_count": 0,
                        "total_sum": 0,
                        "zero_flow_samples": 0,
                        "total_histogram": Counter(),
                        "samples": [],
                    },
                )
                point["sample_count"] += 1
                point["total_sum"] += total
                point["zero_flow_samples"] += int(total == 0)
                point["total_histogram"][total] += 1

                sample = {
                    "total": total,
                    "flow": vector,
                    "date": str(data_day) if data_day is not None else None,
                    "window_start": (
                        int(window_start) if window_start is not None else None
                    ),
                    "metadata": dict(metadata),
                }
                point["samples"].append(sample)

    def _point_report(self, point):
        sample_count = point["sample_count"]
        histogram = point["total_histogram"]
        totals_desc = sorted(histogram, reverse=True)
        max_total = totals_desc[0]
        max_support = histogram[max_total]
        samples = point["samples"]
        top_samples = sorted(
            samples,
            key=lambda item: (
                item["total"],
                item["window_start"] if item["window_start"] is not None else -1,
            ),
            reverse=True,
        )[:2]
        totals = sorted(sample["total"] for sample in samples)
        second_sample_total = (
            top_samples[1]["total"] if len(top_samples) > 1 else None
        )
        second_distinct_total = totals_desc[1] if len(totals_desc) > 1 else None
        max_minus_second = (
            max_total - second_sample_total
            if second_sample_total is not None
            else None
        )
        p25_total = _nearest_rank(totals, 0.25)
        p50_total = _nearest_rank(totals, 0.50)
        p75_total = _nearest_rank(totals, 0.75)
        p90_total = _nearest_rank(totals, 0.90)
        p95_total = _nearest_rank(totals, 0.95)
        median_total = float(median(totals))
        absolute_deviations = sorted(
            abs(total - median_total) for total in totals
        )
        median_absolute_deviation = float(median(absolute_deviations))
        population_stddev = float(pstdev(totals)) if sample_count > 1 else 0.0
        coefficient_of_variation = (
            population_stddev / (point["total_sum"] / sample_count)
            if point["total_sum"] > 0
            else None
        )
        iqr = p75_total - p25_total
        iqr_upper_fence = p75_total + self.iqr_outlier_multiplier * iqr
        distinct_dates = sorted(
            {
                sample["date"]
                for sample in samples
                if sample["date"] is not None
            }
        )
        distinct_windows = {
            (sample["date"], sample["window_start"])
            for sample in samples
        }
        max_support_dates = sorted(
            {
                sample["date"]
                for sample in samples
                if sample["total"] == max_total and sample["date"] is not None
            }
        )
        max_to_second_ratio = (
            round(max_total / second_sample_total, 6)
            if second_sample_total not in (None, 0)
            else None
        )

        flags = []
        if sample_count == 1:
            flags.append("single_sample")
        if sample_count < self.low_support_threshold:
            flags.append("low_support")
        if len(distinct_dates) < self.min_date_support:
            flags.append("low_date_support")

        ratio_is_dominant = (
            second_sample_total == 0 and max_total > 0
        ) or (
            max_to_second_ratio is not None
            and max_to_second_ratio >= self.dominant_max_ratio
        )
        if (
            sample_count >= 2
            and max_support == 1
            and max_minus_second is not None
            and max_minus_second >= self.dominant_max_min_gap
            and ratio_is_dominant
        ):
            flags.append("isolated_dominant_max")
        if (
            sample_count >= 4
            and max_support == 1
            and max_total > iqr_upper_fence
        ):
            flags.append("iqr_high_outlier")

        return {
            "sample_count": sample_count,
            "zero_flow_samples": point["zero_flow_samples"],
            "distinct_window_count": len(distinct_windows),
            "distinct_date_count": len(distinct_dates),
            "dates": distinct_dates,
            "mean_total": round(point["total_sum"] / sample_count, 3),
            "median_total": round(median_total, 3),
            "p25_total": p25_total,
            "p50_total": p50_total,
            "p75_total": p75_total,
            "p90_total": p90_total,
            "p95_total": p95_total,
            "iqr": iqr,
            "iqr_upper_fence": round(iqr_upper_fence, 3),
            "median_absolute_deviation": round(
                median_absolute_deviation,
                3,
            ),
            "population_stddev": round(population_stddev, 3),
            "coefficient_of_variation": (
                round(coefficient_of_variation, 6)
                if coefficient_of_variation is not None
                else None
            ),
            "min_total": min(histogram),
            "max_total": max_total,
            "max_support_count": max_support,
            "max_support_dates": max_support_dates,
            "second_sample_total": second_sample_total,
            "second_distinct_total": second_distinct_total,
            "max_minus_second_sample": max_minus_second,
            "max_to_second_sample_ratio": max_to_second_ratio,
            "total_histogram": {
                str(total): histogram[total]
                for total in sorted(histogram)
            },
            "top_samples": top_samples,
            "flags": flags,
        }

    def build_report(self):
        roads = {}
        for road_id in sorted(self._points):
            road_report = {"directions": {}}
            summary = Counter()
            for direction in sorted(self._points[road_id]):
                points = {}
                for time_key in sorted(
                    self._points[road_id][direction],
                    key=int,
                ):
                    point_report = self._point_report(
                        self._points[road_id][direction][time_key]
                    )
                    points[time_key] = point_report
                    summary["experience_points"] += 1
                    summary["candidate_samples"] += point_report["sample_count"]
                    summary["single_sample_points"] += int(
                        "single_sample" in point_report["flags"]
                    )
                    summary["low_support_points"] += int(
                        "low_support" in point_report["flags"]
                    )
                    summary["isolated_dominant_max_points"] += int(
                        "isolated_dominant_max" in point_report["flags"]
                    )
                    summary["low_date_support_points"] += int(
                        "low_date_support" in point_report["flags"]
                    )
                    summary["iqr_high_outlier_points"] += int(
                        "iqr_high_outlier" in point_report["flags"]
                    )
                    summary["repeated_max_points"] += int(
                        point_report["max_support_count"] > 1
                    )
                road_report["directions"][direction] = points
            road_report["summary"] = dict(summary)
            roads[road_id] = road_report

        return {
            "scope": "current_training_run",
            "selection_changed": False,
            "settings": {
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
        for road_id in sorted(self._points):
            directions = {}
            for direction in sorted(self._points[road_id]):
                directions[direction] = {
                    time_key: list(
                        self._points[road_id][direction][time_key]["samples"]
                    )
                    for time_key in sorted(
                        self._points[road_id][direction],
                        key=int,
                    )
                }
            roads[road_id] = {"directions": directions}

        return {
            "scope": "current_training_run",
            "selection_changed": False,
            "roads": roads,
        }
