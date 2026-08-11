"""Retention maintenance for the persistent lane-level experience pool.

This module is deliberately not scheduled yet. Its file entry point defaults
to a dry run and requires ``--apply`` before it can rewrite a pool file.
"""

from __future__ import annotations

import argparse
import calendar
import copy
import datetime as dt
import json
import os
from collections import Counter

try:
    from lib.data_ANS.experience_pool import _load_json, _write_json_atomic
except ModuleNotFoundError:  # Supports direct execution from data_ANS.
    from experience_pool import _load_json, _write_json_atomic


DEFAULT_RETENTION_MONTHS = 3
DEFAULT_MINIMUM_RECORDS = 100


def _normalize_date(value, *, default_today=False):
    if value is None and default_today:
        return dt.datetime.now().astimezone().date()
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def subtract_calendar_months(value, months):
    """Return the same calendar day ``months`` earlier, clamped by month end."""
    value = _normalize_date(value)
    months = int(months)
    if value is None:
        raise ValueError("value must be an ISO date or date object")
    if months < 1:
        raise ValueError("months must be at least 1")

    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def _record_order(record, original_index):
    record_date = _normalize_date(record.get("date"))
    try:
        window_start = int(record.get("window_start"))
    except (TypeError, ValueError):
        window_start = -1
    return (
        record_date or dt.date.max,
        window_start,
        str(record.get("source_id") or ""),
        int(original_index),
    )


def prune_experience_pool_data(
    pool_data,
    *,
    as_of_date=None,
    retention_months=DEFAULT_RETENTION_MONTHS,
    minimum_records=DEFAULT_MINIMUM_RECORDS,
):
    """Prune expired lane records without taking any lane cell below its floor."""
    if not isinstance(pool_data, dict):
        raise TypeError("experience pool must be a dictionary")
    as_of_date = _normalize_date(as_of_date, default_today=True)
    if as_of_date is None:
        raise ValueError("as_of_date must be an ISO date or date object")
    retention_months = int(retention_months)
    minimum_records = int(minimum_records)
    if minimum_records < 1:
        raise ValueError("minimum_records must be at least 1")
    cutoff_date = subtract_calendar_months(as_of_date, retention_months)

    result = copy.deepcopy(pool_data)
    roads = result.get("roads", result)
    if not isinstance(roads, dict):
        raise TypeError("experience pool roads must be a dictionary")

    summary = Counter()
    lane_cells = {}
    for road_id, directions in roads.items():
        if not isinstance(directions, dict):
            continue
        for direction, time_map in directions.items():
            if not isinstance(time_map, dict):
                continue
            for green_time, lane_map in time_map.items():
                if not isinstance(lane_map, dict):
                    continue
                for lane, records in lane_map.items():
                    if not isinstance(records, list):
                        continue
                    summary["lane_cells_seen"] += 1
                    summary["records_seen"] += len(records)
                    expired = []
                    invalid_or_missing_dates = 0
                    for index, record in enumerate(records):
                        if not isinstance(record, dict):
                            invalid_or_missing_dates += 1
                            continue
                        record_date = _normalize_date(record.get("date"))
                        if record_date is None:
                            invalid_or_missing_dates += 1
                        elif record_date < cutoff_date:
                            expired.append((index, record))

                    total_before = len(records)
                    deletion_budget = max(0, total_before - minimum_records)
                    remove_count = min(len(expired), deletion_budget)
                    ordered_expired = sorted(
                        expired,
                        key=lambda item: _record_order(item[1], item[0]),
                    )
                    removed = ordered_expired[:remove_count]
                    remove_indexes = {index for index, _ in removed}
                    if remove_indexes:
                        lane_map[lane] = [
                            record
                            for index, record in enumerate(records)
                            if index not in remove_indexes
                        ]

                    total_after = total_before - remove_count
                    expired_remaining = len(expired) - remove_count
                    if not expired:
                        decision = "no_expired_records"
                    elif total_before <= minimum_records:
                        decision = "protected_minimum_record_count"
                    elif expired_remaining:
                        decision = "pruned_until_minimum_record_count"
                    else:
                        decision = "all_expired_records_pruned"

                    cell_key = f"{road_id}/{direction}/{green_time}/{lane}"
                    lane_cells[cell_key] = {
                        "decision": decision,
                        "records_before": total_before,
                        "expired_records_before": len(expired),
                        "deletion_budget": deletion_budget,
                        "records_removed": remove_count,
                        "records_after": total_after,
                        "expired_records_remaining": expired_remaining,
                        "invalid_or_missing_date_records": invalid_or_missing_dates,
                        "oldest_removed_date": (
                            str(_normalize_date(removed[0][1].get("date")))
                            if removed
                            else None
                        ),
                        "newest_removed_date": (
                            str(_normalize_date(removed[-1][1].get("date")))
                            if removed
                            else None
                        ),
                    }
                    summary["expired_records_seen"] += len(expired)
                    summary["records_removed"] += remove_count
                    summary["records_retained"] += total_after
                    summary["invalid_or_missing_date_records"] += (
                        invalid_or_missing_dates
                    )
                    if total_before > minimum_records:
                        summary["lane_cells_above_minimum"] += 1
                    if expired:
                        summary["lane_cells_with_expired_records"] += 1
                    if remove_count:
                        summary["lane_cells_pruned"] += 1
                    if total_after < minimum_records:
                        raise AssertionError(
                            f"retention floor violated for {cell_key}: {total_after}"
                        )

    report = {
        "maintenance": "calendar_month_lane_record_retention",
        "as_of_date": as_of_date.isoformat(),
        "cutoff_date_exclusive": cutoff_date.isoformat(),
        "retention_months": retention_months,
        "minimum_records_per_lane_cell": minimum_records,
        "deletion_order": "oldest_date_then_window_start",
        "summary": dict(summary),
        "lane_cells": lane_cells,
    }
    return result, report


def prune_experience_pool_file(
    full_pool_path,
    *,
    output_path=None,
    report_path=None,
    as_of_date=None,
    retention_months=DEFAULT_RETENTION_MONTHS,
    minimum_records=DEFAULT_MINIMUM_RECORDS,
    apply=False,
):
    """Plan or apply retention maintenance to one full-pool JSON file."""
    pool_data = _load_json(full_pool_path)
    if pool_data is None:
        raise FileNotFoundError(full_pool_path)
    result, report = prune_experience_pool_data(
        pool_data,
        as_of_date=as_of_date,
        retention_months=retention_months,
        minimum_records=minimum_records,
    )
    target_path = os.path.abspath(output_path or full_pool_path)
    report.update({
        "full_pool_path": os.path.abspath(full_pool_path),
        "output_path": target_path,
        "applied": bool(apply),
    })
    if apply:
        _write_json_atomic(target_path, result)
    if report_path:
        _write_json_atomic(report_path, report)
    return result, report


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-pool", required=True)
    parser.add_argument("--output")
    parser.add_argument("--report")
    parser.add_argument("--as-of-date")
    parser.add_argument(
        "--retention-months",
        type=int,
        default=DEFAULT_RETENTION_MONTHS,
    )
    parser.add_argument(
        "--minimum-records",
        type=int,
        default=DEFAULT_MINIMUM_RECORDS,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the pruned pool; without this flag the command is dry-run only",
    )
    args = parser.parse_args()
    _, report = prune_experience_pool_file(
        args.full_pool,
        output_path=args.output,
        report_path=args.report,
        as_of_date=args.as_of_date,
        retention_months=args.retention_months,
        minimum_records=args.minimum_records,
        apply=args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
