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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="只读检查在线经验积累、发布与候选使用")
    parser.add_argument("--root", default=".", help="版本目录")
    parser.add_argument("--cross", action="append", help="指定路口，可重复")
    parser.add_argument("--log", help="运行日志路径，默认查找AITC.log或server.log")
    args = parser.parse_args(argv)
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

    target = shadow._target_road_ids()
    print(f"pilot mode: {shadow._pilot_mode()}，目标路口数: {len(target)}")
    if os.environ.get("AITC_FLOW_ALLOCATOR_PILOT_ROADS", "").strip():
        print("目标路口由当前进程环境或.env白名单限定")
    directory = Path(os.environ.get("AITC_FLOW_ALLOCATOR_SHADOW_LOG_DIR") or LOGS_DIR / "shadow")
    latest, by_road, invalid = _load_shadow_summary(directory)
    print(f"影子日志目录: {directory}")
    print(f"最新文件: {latest.name if latest else '未找到'}，"
          f"记录数: {sum(row['count'] for row in by_road.values())}，无法解析行: {invalid}")
    cross_ids = args.cross or sorted(by_road)[:10]
    collection, updates = set(runtime._configured_collection_roads()), runtime._configured_update_roads()

    published_path = runtime._configured_path(
        "AITC_EXPERIENCE_RUNTIME_TABLE", runtime.DEFAULT_STATE_DIR / "online_experience.json",
    )
    read_path = runtime_experience_path()
    published = _read_json(published_path)
    read_table = published if read_path == published_path else _read_json(read_path)
    print(f"发布运行表: {published_path}（{len(published)}个路口）")
    print(f"分配器配置读取表: {read_path}")
    if read_path != published_path:
        print("注意：发布表与分配器读取路径不同，核对是否为有意指定的对照表")
    release = ExperienceReleaseSettings()
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
        print(f"【{group}组】{cross_id} 记录={item.get('count', 0)} "
              f"来源={last.get('selected_schedule_source', '-')} "
              f"质量={last.get('quality_passed', '-')} "
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
        paths = runtime._run_paths(day)
        report = _read_json(Path(paths["run_manifest"]))
        default_status = "未到日更源日期" if day > due_date else "无日任务记录"
        status = report.get("status", default_status)
        covered = set(report.get("pool_collection_road_ids", report.get("target_road_ids", [])))
        uncovered = sorted(set(cross_ids) - covered) if status.startswith("completed") else []
        print(f"  {day} {status} samples={report.get('candidate_count', 0)} "
              f"published={report.get('table_updated', False)} "
              f"flow={Path(paths['flow']).is_file()} extend={Path(paths['extend']).is_file()}"
              + (f" 未覆盖={','.join(uncovered)}" if uncovered else ""))

    candidates = [root / "AITC.log", LOGS_DIR / "AITC.log", root / "server.log", LOGS_DIR / "server.log"]
    log_path = root / args.log if args.log else next((path for path in candidates if path.is_file()), candidates[0])
    fallback = _fallback_stats(log_path)
    print(f"\n运行日志: {log_path}")
    print("fallback_source: " + (", ".join(f"{key or '(空)'}={count}" for key, count in fallback.most_common())
                              or "未找到"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
