"""每决策批次一份时间口径摘要；只读缓存，不改配时输入或写逐车日志。"""

from collections import Counter
import math

from lib.intersection_strategy import supports_online_experience_growth


def _seconds(value, *, milliseconds=True):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number / 1000 if milliseconds and number >= 100_000_000_000 else number


def _summarize(records, field, identify):
    roads, unmapped = {}, Counter()
    invalid_identity = outside_scope = 0
    for cache_time, payload in records or ():
        if not isinstance(payload, dict):
            invalid_identity += 1
            continue
        road, identifier = identify(payload)
        if road is None:
            unmapped[identifier] += 1
            continue
        if not supports_online_experience_growth(road):
            outside_scope += 1
            continue
        row = roads.get(road)
        if row is None:
            row = {
                "records": 0, "invalid_cache_time_records": 0,
                "missing_payload_time_records": 0, "invalid_payload_time_records": 0,
                "cache_timestamp_first": None, "cache_timestamp_last": None,
                "payload_timestamp_first": None, "payload_timestamp_last": None,
                "cache_minus_payload_min_seconds": None, "cache_minus_payload_max_seconds": None,
                "payload_time_backwards_records": 0, "payload_time_repeated_records": 0,
                "_cache_seconds": set(), "_payload_seconds": set(),
                "_previous_payload_time": None, "_lag_sum": 0, "_lag_count": 0,
                "_detectors": Counter(),
            }
            roads[road] = row
        row["records"] += 1
        if field == "ts":
            row["_detectors"][identifier] += 1
        cached = _seconds(cache_time, milliseconds=False)
        event = _seconds(payload.get(field))
        row["invalid_cache_time_records"] += cached is None
        if event is None:
            row["missing_payload_time_records" if payload.get(field) is None
                else "invalid_payload_time_records"] += 1
        for prefix, value in (("cache", cached), ("payload", event)):
            if value is None:
                continue
            row[f"_{prefix}_seconds"].add(int(value))
            first, last = row[f"{prefix}_timestamp_first"], row[f"{prefix}_timestamp_last"]
            row[f"{prefix}_timestamp_first"] = value if first is None else min(first, value)
            row[f"{prefix}_timestamp_last"] = value if last is None else max(last, value)
        if event is not None:
            previous = row["_previous_payload_time"]
            if previous is not None:
                row["payload_time_backwards_records"] += event < previous
                row["payload_time_repeated_records"] += event == previous
            row["_previous_payload_time"] = event
        if cached is not None and event is not None:
            lag = cached - event
            low, high = row["cache_minus_payload_min_seconds"], row["cache_minus_payload_max_seconds"]
            row["cache_minus_payload_min_seconds"] = lag if low is None else min(low, lag)
            row["cache_minus_payload_max_seconds"] = lag if high is None else max(high, lag)
            row["_lag_sum"] += lag
            row["_lag_count"] += 1

    for row in roads.values():
        for prefix in ("cache", "payload"):
            row[f"{prefix}_unique_seconds"] = len(row.pop(f"_{prefix}_seconds"))
            first, last = row[f"{prefix}_timestamp_first"], row[f"{prefix}_timestamp_last"]
            row[f"{prefix}_span_seconds"] = round(last - first, 3) if first is not None else 0
        count, total = row.pop("_lag_count"), row.pop("_lag_sum")
        row["cache_minus_payload_mean_seconds"] = round(total / count, 3) if count else None
        row.pop("_previous_payload_time")
        detectors = row.pop("_detectors")
        if detectors:
            row["detector_records"] = dict(detectors)
        for key, value in row.items():
            if isinstance(value, float):
                row[key] = round(value, 3)
    return {"cache_timestamps_available": records is not None, "by_road": roads,
            "unmapped_identifiers": dict(unmapped), "invalid_identity_records": invalid_identity,
            "outside_scope_records": outside_scope}


def summarize_input_timebases(flow_records, extend_records, location_map):
    """对照FLOW.ts、EXTEND.time与落盘后入库时间；差值不能直接认定网络延迟。"""
    def flow_identity(payload):
        raw = payload.get("jtll_ddbh")
        try:
            detector = None if isinstance(raw, bool) else int(raw)
        except (TypeError, ValueError, OverflowError):
            detector = None
        location = location_map.get(detector)
        return (str(location[0]) if location else None,
                str(detector) if detector is not None else "<invalid>")

    def extend_identity(payload):
        raw = payload.get("CrossId")
        return (str(raw), str(raw)) if isinstance(raw, (str, int)) and not isinstance(raw, bool) else (None, "<invalid>")

    return {"scope": "19_and_onboarded_platform_roads",
            "sample_scope": "cache_snapshot_before_aggregation",
            "cache_timestamp_semantics": "cache_insertion_after_persistence",
            "payload_timestamp_semantics": "unverified_source_time",
            "flow": _summarize(flow_records, "ts", flow_identity),
            "extend": _summarize(extend_records, "time", extend_identity)}
