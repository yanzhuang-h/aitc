"""按日期区间补跑经验池，用于新路口历史数据训练。

在版本目录执行（读取 .env 中的 AITC_DATA_ROOT）：
  python tools/backfill_experience.py \
    --start 2026-11-09 --end 2026-11-12 \
    --roads 1700267,1700546,2703317,1700548 \
    --min-samples 3 --apply

默认只预览；加 --apply 才真正更新经验表。
--force 会删除对应日期的运行记录，避免旧的 skipped_* 记录阻止重跑。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


def _dates(start: dt.date, end: dt.date):
    current = start
    while current <= end:
        yield current
        current += dt.timedelta(days=1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="按日期区间补跑经验池")
    parser.add_argument("--root", default=".", help="版本目录")
    parser.add_argument("--start", required=True, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--roads", required=True, help="逗号分隔的路口 ID")
    parser.add_argument("--min-samples", type=int, default=30, help="最小样本数")
    parser.add_argument("--force", action="store_true", help="删除已有运行记录后重跑")
    parser.add_argument("--apply", action="store_true", help="实际执行（默认只预览）")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import os

    roads = ",".join(item.strip() for item in args.roads.split(",") if item.strip())
    os.environ["AITC_EXPERIENCE_POOL_ROADS"] = roads
    os.environ["AITC_EXPERIENCE_TABLE_UPDATE_ROADS"] = roads
    os.environ["AITC_EXPERIENCE_POOL_MIN_SAMPLES"] = str(max(1, args.min_samples))

    import lib.data_ANS.experience_runtime as runtime

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    print(f"路口: {roads}")
    print(f"日期: {start} ~ {end}，最小样本: {args.min_samples}")

    for day in _dates(start, end):
        paths = runtime._run_paths(day)
        flow_ok = Path(paths["flow"]).is_file()
        extend_ok = Path(paths["extend"]).is_file()
        print(f"[{day}] flow={flow_ok} extend={extend_ok}")
        if not args.apply:
            continue
        if args.force:
            manifest = Path(paths["run_manifest"])
            if manifest.exists():
                manifest.unlink()
                print(f"  已删除运行记录: {manifest}")
        report = runtime.run_experience_pool_day(day)
        print(
            f"  status={report.get('status')} "
            f"candidates={report.get('candidate_count')} "
            f"table_updated={report.get('table_updated')}"
        )

    if args.apply:
        from app.paths import EXPERIENCE_POOL_DIR

        table = EXPERIENCE_POOL_DIR / "online_experience.json"
        data = json.loads(table.read_text(encoding="utf-8-sig")) if table.is_file() else {}
        hits = [road for road in roads.split(",") if road in data]
        print(f"经验表: {table}（{len(data)} 个路口）")
        print(f"本次路口已收录: {hits}")
    else:
        print("预览完成；确认后加 --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
