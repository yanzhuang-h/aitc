"""只读检查经验任务、发布文件与在线候选选择，不触发训练或修改经验。

在版本目录执行：
  python tools/check_online_learning.py --cross 1700125 --cross 1700240

读取当前进程配置及最近日志；不能单独证明另一生产进程已加载或信号机执行。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo


def _load_shadow_summary(directory):
    files = sorted(directory.glob("flow_time_allocator_*.jsonl"))
    if not files:
        return None, {}, 0
    latest = files[-1]
    by_road = defaultdict(lambda: {"count": 0, "last": None})
    invalid = 0
    with latest.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            if not isinstance(record, dict) or not record.get("road_id"):
                invalid += 1
                continue
            row = by_road[str(record["road_id"])]
            row["count"] += 1
            row["last"] = record
    return latest, dict(by_road), invalid


def _fallback_stats(path):
    if not path.is_file():
        return Counter()
    pattern = re.compile(r'"fallback_source"\s*:\s*"([^"]*)"')
    counter = Counter()
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            counter.update(pattern.findall(line))
    return counter


def _read_json(path):
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream)


_LOCAL_ZONE = ZoneInfo("Asia/Shanghai")


def _time(value):
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc)
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_LOCAL_ZONE)


def _first_file(*paths):
    return next((path for path in paths if path.is_file()), paths[0])


def _records(path, id_field, roads, *, marker=None):
    if not path.is_file():
        return
    roads_pattern = "|".join(re.escape(road) for road in sorted(roads))
    id_pattern = re.compile(rb'"' + id_field.encode() + rb'"\s*:\s*"(' + roads_pattern.encode() + rb')"')
    with path.open("rb") as stream:
        for line in stream:
            if (marker is not None and marker not in line) or not id_pattern.search(line):
                continue
            try:
                value = json.loads(line[line.find(b"{") :])
            except (UnicodeError, ValueError):
                continue
            if isinstance(value, dict):
                yield value


def _in_window(value, start, end):
    try:
        stamp = _time(value)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return stamp if start <= stamp < end else None


def _uses_changed_experience(candidate, current, previous):
    for direction, decision in candidate.get("decisions", {}).items():
        seconds = decision.get("table_green_time", 0)
        if decision.get("requested_flow", 0) > 0 and seconds > 0 and not decision.get("fallback_source"):
            point = current.get(direction, {}).get(str(seconds))
            if point is not None and point != previous.get(direction, {}).get(str(seconds)):
                return True
    return False


def _daily_evidence(day, roads, runtime, log_dir):
    paths = runtime._run_paths(day, log_dir=log_dir)
    report = _read_json(paths["run_manifest"])
    candidate_path = Path(report.get("artifacts", {}).get("candidates", paths["candidates"]))
    candidates = _read_json(candidate_path).get("roads")
    covered = set(report.get("pool_collection_road_ids", report.get("target_road_ids", [])))
    return {
        "source_date": day.isoformat(),
        "source_pair": runtime._source_pair_status(paths, day) or {"status": "complete_tail"},
        "status": report.get("status", "no_report"),
        "table_updated": report.get("table_updated"),
        "release_id": (report.get("release") or {}).get("release_id"),
        "roads": {road: {
            "covered": road in covered,
            "missing_cross": road in report.get("missing_crosses", []),
            "requires_chronological_rebuild": road in report.get("rebuild_required_roads", []),
            "qualified_samples": sum(
                len(samples)
                for times in candidates.get(road, {}).get("directions", {}).values()
                for samples in times.values()
            ) if candidates is not None and road in covered else None,
        } for road in roads},
    }


def _export_evidence(args, log_dir, directory, log_path, runtime, shadow, release, road_group):
    from lib.data_ANS.experience_reader import runtime_experience_path
    from lib.data_ANS.experience_release import _canonical_hash

    start, end = args.start, args.end
    roads = sorted(set(args.cross))
    first_day = start.astimezone(_LOCAL_ZONE).date()
    last_day = (end - dt.timedelta(microseconds=1)).astimezone(_LOCAL_ZONE).date()
    days = [first_day + dt.timedelta(days=offset) for offset in range((last_day - first_day).days + 1)]
    active = _read_json(release.active_manifest_path)
    table_path = runtime_experience_path()
    table = _read_json(table_path)
    consistent = bool(table_path.is_file() and active.get("runtime_path") and Path(active["runtime_path"]).resolve() == table_path
                      and _canonical_hash(table) == active.get("active_sha256"))
    previous_path = active.get("rollback_version_path")
    previous = _read_json(Path(previous_path)) if previous_path else {}
    previous_known = ("previous_sha256" in active and active["previous_sha256"] is None) or (
        bool(previous) and _canonical_hash(previous) == active.get("previous_sha256")
    )
    created_at = _in_window(active.get("created_at_utc"), dt.datetime.min.replace(tzinfo=dt.timezone.utc), end)
    fingerprints = {road: _canonical_hash(table[road]) for road in roads if table.get(road)}
    target = shadow._target_road_ids()
    road_reports = {road: {
        "group": road_group(road), "configured_mode": shadow._pilot_mode(road), "in_candidate_scope": road in target,
        "candidate_rounds": 0, "shadow_passed_rounds": 0, "new_selected_rounds": 0,
        "current_release_row_seen_rounds": 0, "used_changed_experience_rounds": 0,
        "current_release_changed_road": (previous.get(road) != table.get(road)) if consistent and previous_known else None,
        "rejections": Counter(), "send_records": 0,
        "sent_program_counts": Counter(), "empty_phase_send_records": 0,
    } for road in roads}
    sources = {"decision_log_found": log_path.is_file(), "shadow_dates_found": [], "send_dates_found": []}
    sent = {road: set() for road in roads}
    for day in days:
        path = _first_file(log_dir / "send" / f"{day}_send.txt", log_dir / f"{day}_send.txt")
        if path.is_file():
            sources["send_dates_found"].append(str(day))
        for item in _records(path, "id", roads):
            stamp = _in_window(item.get("AITC_SYS_TS"), start, end)
            plan = item.get("additional", {}).get("tlLogic", {})
            road = plan.get("id")
            if stamp is None or road not in road_reports:
                continue
            fingerprint = item.get("AITC_PLAN_SHA256") or _canonical_hash(plan)
            batch_id = item.get("AITC_DECISION_BATCH_ID")
            sent[road].add((batch_id, fingerprint))
            entry = road_reports[road]
            entry["send_records"] += 1
            program_id = plan.get("programID")
            green_seconds = [phase.get("duration") for phase in plan.get("phase", [])]
            if not green_seconds:
                entry["empty_phase_send_records"] += 1
            elif program_id is not None:
                entry["sent_program_counts"][str(program_id)] += 1
            local_time = stamp.astimezone(_LOCAL_ZONE).isoformat()
            if "latest_send" not in entry or local_time >= entry["latest_send"]["at"]:
                entry["latest_send"] = {
                    "at": local_time, "program_id": program_id, "green_seconds": green_seconds,
                    "batch_id": batch_id, "plan_sha256": fingerprint, "decision": None,
                    "logged_release_id": item.get("AITC_EXPERIENCE_PROVENANCE", {}).get("release_id"),
                }

    latest_by_batch = {
        (road, latest["batch_id"]): latest
        for road, entry in road_reports.items()
        if (latest := entry.get("latest_send")) and latest["batch_id"]
    }
    selected_batches = set()
    latest_candidates = {}
    for day in days:
        path = _first_file(directory / f"flow_time_allocator_{day}.jsonl",
                           log_dir / f"flow_time_allocator_{day}.jsonl")
        if path.is_file():
            sources["shadow_dates_found"].append(str(day))
        for item in _records(path, "road_id", roads):
            road = item["road_id"]
            batch_key = (road, item.get("batch_id"))
            rejected = item.get("selection_fallback_reason") or item.get("candidate_rejection_reason")
            if batch_key in latest_by_batch:
                latest_candidates[batch_key] = {
                    "candidate_source": item.get("selected_schedule_source"),
                    "candidate_rejection_reason": rejected,
                }
            stamp = _in_window(item.get("observed_at"), start, end)
            if stamp is None:
                continue
            entry = road_reports[road]
            entry["candidate_rounds"] += 1
            if rejected:
                entry["rejections"][rejected] += 1
            elif (item.get("runtime_mode") == "shadow" and item.get("status") == "ok"
                  and item.get("quality_passed") is True and item.get("flow_input", {}).get("selected_timestamp_records", 0) > 0):
                entry["shadow_passed_rounds"] += 1
            selected = item.get("selected_schedule_source") == "new"
            if selected:
                entry["new_selected_rounds"] += 1
                if item.get("batch_id"):
                    selected_batches.add(batch_key)
            if (consistent and created_at is not None and stamp >= created_at and road in fingerprints
                    and item.get("experience_road_sha256") == fingerprints[road]):
                entry["current_release_row_seen_rounds"] += 1
                if (selected and entry["current_release_changed_road"]
                        and _uses_changed_experience(item, table[road], previous.get(road, {}))):
                    entry["used_changed_experience_rounds"] += 1

    matched = {road: set() for road in roads}
    if selected_batches or latest_by_batch:
        for item in _records(log_path, "intersection_id", roads, marker=b'"aitc.decision"'):
            fingerprint = item.get("plan_sha256")
            if item.get("status") != "published" or not fingerprint:
                continue
            road, batch_id = item["intersection_id"], item.get("batch_id")
            batch_key = (road, batch_id)
            if batch_key in selected_batches and (
                (batch_id, fingerprint) in sent[road] or (None, fingerprint) in sent[road]
            ):
                matched[road].add(fingerprint)
            latest = latest_by_batch.get(batch_key)
            if latest is not None and latest["plan_sha256"] == fingerprint:
                safety = item.get("safety_report") or {}
                latest["decision"] = {
                    **latest_candidates.get(batch_key, {}),
                    "safety_status": safety.get("safety_status"),
                    "safety_fallback_source": safety.get("fallback_source"),
                    "safety_fallback_reason": safety.get("fallback_reason"),
                }

    if any(latest["decision"] is not None for latest in latest_by_batch.values()):
        for item in _records(log_path, "cross_id", roads, marker=b"flow_control {"):
            latest = latest_by_batch.get((item["cross_id"], item.get("batch_id")))
            if latest is not None and latest["decision"] is not None:
                latest["decision"]["coordinator_timing_source"] = item.get("timing_source")
                latest["decision"]["coordinator_fallback"] = item.get("fallback")

    for road, plans in sent.items():
        road_reports[road]["distinct_sent_plans"] = len({fingerprint for _, fingerprint in plans})
        road_reports[road]["distinct_sent_plans_matching_final"] = len(matched[road])
    return {
        "schema_version": 1, "start": start.isoformat(), "end_exclusive": end.isoformat(),
        "sources": sources, "active_release_id": active.get("release_id"),
        "active_source_date": active.get("source_metadata", {}).get("source_date"),
        "active_manifest_matches_read_table": consistent,
        "source_days": [_daily_evidence(last_day - dt.timedelta(days=offset), roads, runtime, log_dir)
                        for offset in range(runtime.DEFAULT_CATCHUP_DAYS, 0, -1)],
        "roads": road_reports,
        "send_matching": "带批次号的记录按路口、批次和方案指纹关联，旧日志仅比较方案内容指纹",
        "signal_controller_execution": "需要现场执行记录",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="只读检查在线经验积累、发布与候选使用")
    parser.add_argument("--root", default=".", help="版本目录")
    parser.add_argument("--cross", action="append", help="指定路口，可重复")
    parser.add_argument("--log", help="运行日志路径，优先查找server.log，兼容旧版AITC.log")
    parser.add_argument("--log-dir", type=Path, help="另指定日志目录，可检查运维回传副本")
    parser.add_argument("--export", type=Path, help="生成一次性的取证 JSON 文件")
    parser.add_argument("--start", type=_time, help="记录开始时间，北京时间或带时区的 ISO 时间")
    parser.add_argument("--end", type=_time, help="记录结束时间，不含结束时刻")
    args = parser.parse_args(argv)
    if args.export is not None and (not args.cross or args.start is None or args.end is None or args.start >= args.end):
        parser.error("--export 需要 --cross 和有效的 --start、--end")
    export_path = args.export.resolve() if args.export else None
    if export_path is not None and export_path.exists():
        parser.error(f"导出文件已存在: {export_path}")
    root = Path(args.root).resolve()
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app.config import ExperienceReleaseSettings, _load_dotenv

    _load_dotenv(root / ".env")
    from app.paths import LOGS_DIR
    from lib.data_ANS import experience_runtime as runtime, flow_allocator_shadow as shadow
    from lib.data_ANS.experience_reader import runtime_experience_path
    from lib.data_ANS.experience_release import _canonical_hash
    from lib.road_groups import road_group

    log_dir = args.log_dir or Path(os.environ.get("AITC_RUNTIME_OUTPUT_DIR") or LOGS_DIR)
    directory = (log_dir / "shadow" if args.log_dir else
                 Path(os.environ.get("AITC_FLOW_ALLOCATOR_SHADOW_LOG_DIR") or LOGS_DIR / "shadow"))
    candidates = [root / "server.log", log_dir / "server.log", root / "AITC.log", log_dir / "AITC.log"]
    log_path = root / args.log if args.log else _first_file(*candidates)
    release = ExperienceReleaseSettings()
    if export_path is not None:
        report = _export_evidence(args, log_dir, directory, log_path, runtime, shadow, release, road_group)
        with export_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(export_path)
        return 0

    target = shadow._target_road_ids()
    print(f"pilot mode: {shadow._pilot_mode()}，目标路口数: {len(target)}")
    if os.environ.get("AITC_FLOW_ALLOCATOR_PILOT_ROADS", "").strip():
        print("目标路口由当前进程环境或.env白名单限定")
    latest, by_road, invalid = _load_shadow_summary(directory)
    print(f"影子日志目录: {directory}")
    print(f"最新文件: {latest.name if latest else '未找到'}，"
          f"记录数: {sum(row['count'] for row in by_road.values())}，无法解析行: {invalid}")
    cross_ids = args.cross or sorted(by_road)[:10]
    collection, updates = set(runtime._configured_collection_roads()), runtime._configured_update_roads()

    published_path = runtime.published_experience_path()
    read_path = runtime_experience_path()
    published = _read_json(published_path)
    read_table = published if read_path == published_path else _read_json(read_path)
    print(f"发布运行表: {published_path}（{len(published)}个路口）")
    print(f"分配器配置读取表: {read_path}")
    if read_path != published_path:
        print("注意：发布表与分配器读取路径不同，核对是否为有意指定的对照表")
    manifest = _read_json(release.active_manifest_path)
    published_hash = _canonical_hash(published) if published_path.is_file() else None
    consistent = bool(published_hash and manifest.get("active_sha256") == published_hash
                      and Path(manifest.get("runtime_path", "")).resolve() == published_path)
    print(f"发布清单: {release.active_manifest_path}，与发布表一致: {consistent}")
    if Path(str(release.active_manifest_path) + ".pending").exists():
        print("存在待完成的发布记录，需核对发布任务结果")

    for cross_id in cross_ids:
        group = road_group(cross_id) or "历史/其他"
        item = by_road.get(cross_id, {})
        last = item.get("last") or {}
        flow_input = last.get("flow_input")
        flow_points = flow_input.get("selected_timestamp_records", "-") if isinstance(flow_input, dict) else "-"
        print(f"【{group}组】{cross_id} 记录={item.get('count', 0)} "
              f"模式={shadow._pilot_mode(cross_id)} 来源={last.get('selected_schedule_source', '-')} "
              f"阶段反馈达标={last.get('quality_passed', '-')} "
              f"窗口内FLOW时间点数={flow_points} "
              f"原因={last.get('selection_fallback_reason') or '-'}")
        print(f"  范围: 候选={cross_id in target} 积累={cross_id in collection} 发布={cross_id in updates}；"
              f"读取表方向点数: { {direction: len(points) for direction, points in read_table.get(cross_id, {}).items()} }")
        logged_hash = last.get("experience_road_sha256")
        if logged_hash:
            print(f"  最新日志经验指纹与当前读取文件一致: "
                  f"{logged_hash == _canonical_hash(read_table.get(cross_id, {}))}")

    today = dt.date.today()
    due_date = runtime.ExperiencePoolScheduler.source_date_for_run(today)
    print("\n最近7个完整日的积累记录（无日记录不等于未入池，不自动补跑）:")
    for offset in range(7, 0, -1):
        day = today - dt.timedelta(days=offset)
        paths = runtime._run_paths(day, log_dir=log_dir)
        report = _read_json(Path(paths["run_manifest"]))
        default_status = "未到日更源日期" if day > due_date else "无日任务记录"
        status = report.get("status", default_status)
        covered = set(report.get("pool_collection_road_ids", report.get("target_road_ids", [])))
        uncovered = sorted(set(cross_ids) - covered) if status.startswith("completed") else []
        print(f"  {day} {status} samples={report.get('candidate_count', 0)} "
              f"published={report.get('table_updated', False)} "
              f"flow={Path(paths['flow']).is_file()} extend={Path(paths['extend']).is_file()}"
              + (f" 未覆盖={','.join(uncovered)}" if uncovered else ""))

    fallback = _fallback_stats(log_path)
    print(f"\n运行日志: {log_path}")
    print("fallback_source: " + (", ".join(f"{key or '(空)'}={count}" for key, count in fallback.most_common())
                              or "未找到"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
