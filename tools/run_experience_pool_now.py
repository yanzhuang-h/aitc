"""手动执行单日经验积累，复用backfill_experience的配置、发布与去重入口。

默认T-1、最小样本30；此命令立即执行，周范围补训使用backfill_experience.py。
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import sys


def _resolve_date(value: str | None) -> dt.date:
    today = dt.date.today()
    if not value or value == "today":
        return today
    if value in {"yesterday", "T-1", "t-1"}:
        return today - dt.timedelta(days=1)
    if value in {"T-2", "t-2"}:
        return today - dt.timedelta(days=2)
    return dt.date.fromisoformat(value)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="手动执行单日经验池更新（立即执行）")
    parser.add_argument("--root", default=".", help="版本目录")
    parser.add_argument("--source-date", default="T-1", help="today/yesterday/T-1/T-2或YYYY-MM-DD")
    parser.add_argument("--min-samples", type=int, default=30, help="正式补训保持默认30")
    parser.add_argument("--roads", default="online", help="默认19组及平台路口，或指定批次/ID")
    parser.add_argument("--force", action="store_true", help="锁内复查日记录，已入池样本仍去重")
    args = parser.parse_args(argv)
    source_date = _resolve_date(args.source_date).isoformat()
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from tools.backfill_experience import main as backfill

    return backfill([
        "--root", args.root, "--start", source_date, "--end", source_date,
        "--roads", args.roads, "--min-samples", str(args.min_samples), "--apply",
        *(["--force"] if args.force else []),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
