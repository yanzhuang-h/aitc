"""快速触发一次经验池更新，用于验证在线学习链路。

只用于测试/验证：默认取当天、最小样本数 3、可指定路口。
正式训练仍由每天 12:00 的 T-2 任务执行。

用法（版本目录内）：
  python tools/run_experience_pool_now.py --source-date today --min-samples 3
  python tools/run_experience_pool_now.py --source-date 2026-11-09 --force
  python tools/run_experience_pool_now.py --roads 1700240,1700062 --min-samples 2
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path


def _resolve_date(value: str | None) -> dt.date:
    today = dt.date.today()
    if not value or value == "today":
        return today
    if value == "yesterday":
        return today - dt.timedelta(days=1)
    if value in {"T-1", "t-1"}:
        return today - dt.timedelta(days=1)
    if value in {"T-2", "t-2"}:
        return today - dt.timedelta(days=2)
    return dt.date.fromisoformat(value)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="快速触发经验池更新（测试用）")
    parser.add_argument("--root", default=".", help="版本目录")
    parser.add_argument("--source-date", default="today",
                        help="today/yesterday/T-1/T-2 或 YYYY-MM-DD")
    parser.add_argument("--min-samples", type=int, default=3,
                        help="最小样本数（默认 3，生产为 30）")
    parser.add_argument("--roads", default="",
                        help="只处理这些路口（逗号分隔），默认使用代码集合")
    parser.add_argument("--force", action="store_true",
                        help="忽略已完成的运行记录，强制重跑")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    os.environ["AITC_EXPERIENCE_POOL_MIN_SAMPLES"] = str(max(1, args.min_samples))
    if args.roads.strip():
        roads = ",".join(item.strip() for item in args.roads.split(",") if item.strip())
        os.environ["AITC_EXPERIENCE_POOL_ROADS"] = roads
        os.environ["AITC_EXPERIENCE_TABLE_UPDATE_ROADS"] = roads
        print(f"仅处理路口: {roads}")

    import lib.data_ANS.experience_runtime as runtime

    source_date = _resolve_date(args.source_date)
    if args.force:
        manifest = Path(runtime._run_paths(source_date)["run_manifest"])
        if manifest.exists():
            manifest.unlink()
            print(f"已删除运行记录: {manifest}")

    print(f"源日期: {source_date}，最小样本数: {os.environ['AITC_EXPERIENCE_POOL_MIN_SAMPLES']}")
    report = runtime.run_experience_pool_day(source_date)
    summary = {
        key: report.get(key)
        for key in (
            "status",
            "source_date",
            "target_road_ids",
            "table_update_road_ids",
            "observation_count",
            "candidate_count",
            "minimum_sample_count",
            "pool_committed",
            "table_updated",
        )
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if report.get("status") == "skipped_missing_source_data":
        print("缺少源数据（flow/extend），请确认 logs_data 中对应日期的文件：")
        for path in report.get("missing_files", []):
            print("  -", path)

    table = root / "lib" / "experience_pool" / "online_experience.json"
    if table.is_file():
        mtime = dt.datetime.fromtimestamp(table.stat().st_mtime)
        print(f"经验表: {table}（更新于 {mtime:%Y-%m-%d %H:%M:%S}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
