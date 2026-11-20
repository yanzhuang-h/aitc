"""生产经验补训默认处理在线学习范围内最近七个完整日的 FLOW 和 EXTEND。

在版本目录执行：
  python tools/backfill_experience.py
  python tools/backfill_experience.py --apply
  python tools/backfill_experience.py --start 2026-11-09 --end 2026-11-15 --roads 19 --apply

默认只预览；--apply才积累样本并按原门槛发布。--force仅复查日记录，
已入池样本仍去重，不会重建已处理历史或重复加权。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path


def _dates(start: dt.date, end: dt.date):
    current = start
    while current <= end:
        yield current
        current += dt.timedelta(days=1)


def _date_range(parser, args):
    if args.start is not None or args.end is not None:
        if args.start is None or args.end is None or args.days is not None:
            parser.error("--start与--end须同时指定，不能与--days混用")
        start, end = args.start, args.end
    else:
        days = 7 if args.days is None else args.days
        if days < 1:
            parser.error("--days必须大于0")
        end = dt.date.today() - dt.timedelta(days=1)
        start = end - dt.timedelta(days=days - 1)
    if start > end:
        parser.error("起始日期不能晚于结束日期")
    return start, end


def _road_ids(value, root):
    from lib.intersection_strategy import PLATFORM_PHASE_ROAD_IDS
    from lib.road_groups import TONGZHOU_19, TONGZHOU_49

    selection = value.strip().lower()
    if selection == "online":
        return sorted(TONGZHOU_19 | PLATFORM_PHASE_ROAD_IDS)
    if selection in {"19", "49"}:
        return sorted(TONGZHOU_19 if selection == "19" else TONGZHOU_49)
    if selection == "all":
        # 保留旧命令的范围；all从未表示19/49全部路口。
        overrides = root / "lib" / "plan_id_overrides.json"
        return sorted(json.loads(overrides.read_text(encoding="utf-8-sig")))
    return sorted({item.strip() for item in value.split(",") if item.strip()})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="按日期区间补跑在线经验池（默认最近7个完整日）")
    parser.add_argument("--root", default=".", help="版本目录，配置相对路径以此为基准")
    parser.add_argument("--start", type=dt.date.fromisoformat, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=dt.date.fromisoformat, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--days", type=int, help="最近完整天数，默认7，不含当天")
    parser.add_argument("--roads", default="online",
                        help="online=19组及平台路口，19/49=指定批次，或逗号分隔ID；all保留旧登记范围")
    parser.add_argument("--min-samples", type=int, default=30, help="最小样本数，正式补训保持默认30")
    parser.add_argument("--force", action="store_true", help="锁内复查日记录，已入池样本仍去重")
    parser.add_argument("--apply", action="store_true", help="实际执行（默认只预览）")
    args = parser.parse_args(argv)
    start, end = _date_range(parser, args)
    if args.min_samples < 1:
        parser.error("--min-samples必须大于0")

    root = Path(args.root).resolve()
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app.config import ExperienceReleaseSettings, _load_dotenv

    _load_dotenv(root / ".env")
    roads = _road_ids(args.roads, root)
    if not roads:
        parser.error("路口范围不能为空")
    os.environ["AITC_EXPERIENCE_POOL_ROADS"] = ",".join(roads)
    os.environ["AITC_EXPERIENCE_TABLE_UPDATE_ROADS"] = ",".join(roads)
    os.environ["AITC_EXPERIENCE_POOL_MIN_SAMPLES"] = str(args.min_samples)

    from lib.data_ANS import experience_runtime as runtime
    from lib.data_ANS.experience_reader import runtime_experience_path
    from lib.intersection_strategy import PLATFORM_PHASE_ROAD_IDS
    from lib.road_groups import TONGZHOU_19, TONGZHOU_49

    table = runtime.published_experience_path()
    read_table = runtime_experience_path()
    selected = set(roads)
    known_batches = TONGZHOU_19 | TONGZHOU_49
    other_platform_roads = PLATFORM_PHASE_ROAD_IDS - known_batches
    print(f"路口: {','.join(roads)}")
    print(f"范围: 共{len(roads)}个，19组{len(selected & TONGZHOU_19)}个，"
          f"49组{len(selected & TONGZHOU_49)}个，"
          f"其他平台路口{len(selected & other_platform_roads)}个，"
          f"其他路口{len(selected - known_batches - other_platform_roads)}个")
    print(f"日期: {start} ~ {end}，最小样本: {args.min_samples}")
    print(f"发布运行表: {table}")
    print(f"版本清单: {ExperienceReleaseSettings().active_manifest_path}")
    if read_table != table:
        print(f"注意：分配器实际读取另一份表: {read_table}")

    skipped = False
    source_issue_labels = {"missing": "缺文件", "incomplete": "未收齐", "unreadable": "无法读取"}
    for day in _dates(start, end):
        paths = runtime._run_paths(day)
        pending = runtime._source_pair_status(paths, day)
        input_check = "通过日末检查"
        if pending:
            details = "、".join(
                f"{'/'.join(pending[key]).upper()} {label}"
                for key, label in source_issue_labels.items() if key in pending
            )
            input_check = f"待收齐（{details}）"
        previous = runtime._existing_terminal_manifest(
            paths["run_manifest"], (Path(paths["flow"]), Path(paths["extend"])),
            target_road_ids=roads,
        )
        print(f"[{day}] 自动补跑预检={input_check} "
              f"记录={previous.get('status') if previous else '待检查'}")
        if not args.apply:
            continue
        report = runtime.run_experience_pool_day(day, recheck=args.force)
        status = str(report.get("status", ""))
        missing_crosses = report.get("missing_crosses", [])
        rebuild_roads = report.get("rebuild_required_roads", [])
        skipped |= status.startswith("skipped") or bool(missing_crosses or rebuild_roads)
        if rebuild_roads:
            print(f"  需要顺序重建的路口: {','.join(rebuild_roads)}")
        if missing_crosses:
            print(f"  跳过缺配置路口: {','.join(missing_crosses)}")
        outcome = runtime._run_execution_summary(report)
        print(f"  status={outcome.get('status', status)} candidates={report.get('candidate_count', 0)} "
              f"table_updated={outcome.get('table_updated', False)}")
        print(f"  报告: {paths['run_manifest']}")

    if args.apply:
        data = json.loads(table.read_text(encoding="utf-8-sig")) if table.is_file() else {}
        print(f"经验表: {table}（{len(data)}个路口）")
        print(f"本次路口已收录: {[road for road in roads if road in data]}")
    else:
        print("预览完成；正式执行加--apply")
    return 1 if skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
