"""诊断在线学习（pilot 分配器）是否在正常工作。

在版本目录执行：
    python tools/check_online_learning.py
    python tools/check_online_learning.py --cross 1700240 --cross 1700062

检查项：
  1. pilot 模式与目标路口集合（是否被 .env 覆盖）
  2. logs_data/shadow 的最新影子记录（new/legacy、拒绝原因）
  3. AITC.log 中 fallback_source 分布（timetable 多说明走了兜底时刻表）
  4. lib/experience_pool/online_experience.json 是否更新
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def _read_env(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    path = root / ".env"
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def _load_shadow_records(root: Path, env: dict[str, str]):
    directory = Path(
        env.get("AITC_FLOW_ALLOCATOR_SHADOW_LOG_DIR")
        or root / "logs_data" / "shadow"
    )
    files = sorted(directory.glob("flow_time_allocator_*.jsonl"))
    if not files:
        return directory, None, []
    latest = files[-1]
    records = []
    for line in latest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return directory, latest, records


def _fallback_stats(root: Path, log_name: str) -> Counter:
    path = root / log_name
    if not path.is_file():
        return Counter()
    pattern = re.compile(r'"fallback_source":"([^"]*)"')
    counter = Counter()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        counter.update(pattern.findall(line))
    return counter


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="检查在线学习是否生效")
    parser.add_argument("--root", default=".", help="版本目录")
    parser.add_argument("--cross", action="append", default=None, help="指定路口")
    parser.add_argument("--log", default="AITC.log", help="运行日志文件名")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    env = _read_env(root)

    import sys

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import lib.data_ANS.flow_allocator_shadow as shadow

    mode = shadow._pilot_mode()
    target = shadow._target_road_ids()
    override = env.get("AITC_FLOW_ALLOCATOR_PILOT_ROADS", "")
    print(f"pilot mode: {mode}")
    print(f"目标路口数: {len(target)}")
    if override:
        print(f"注意: .env 中 AITC_FLOW_ALLOCATOR_PILOT_ROADS 已覆盖默认集合（{len(override.split(','))} 项）")
    else:
        print("AITC_FLOW_ALLOCATOR_PILOT_ROADS 未设置，使用代码默认集合")

    directory, latest, records = _load_shadow_records(root, env)
    print(f"影子日志目录: {directory}")
    if latest is None:
        print("未找到影子日志：pilot 可能未运行或该路口不在目标集合")
        return 0
    print(f"最新文件: {latest.name}，记录数: {len(records)}")

    by_road: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_road[str(record.get("road_id"))].append(record)

    cross_ids = args.cross or sorted(by_road)[:10]
    print("\n路口        记录数  最后来源      状态      拒绝原因")
    for cross_id in cross_ids:
        items = by_road.get(cross_id, [])
        if not items:
            print(f"{cross_id:10} 0        -             -         -")
            continue
        last = items[-1]
        print(
            f"{cross_id:10} {len(items):<7} "
            f"{str(last.get('selected_schedule_source')):<13} "
            f"{str(last.get('status')):<9} "
            f"{last.get('selection_fallback_reason') or ''}"
        )

    fallback = _fallback_stats(root, args.log)
    if fallback:
        print("\nAITC.log fallback_source 分布:")
        for key, count in fallback.most_common():
            print(f"  {key or '(空)'}: {count}")
    else:
        print(f"\n未在 {args.log} 找到 fallback_source 字段")

    from app.paths import EXPERIENCE_POOL_DIR

    table = EXPERIENCE_POOL_DIR / "online_experience.json"
    if table.is_file():
        import datetime

        mtime = datetime.datetime.fromtimestamp(table.stat().st_mtime)
        data = json.loads(table.read_text(encoding="utf-8-sig"))
        print(f"\n经验表: {table}（{len(data)} 个路口，更新于 {mtime:%Y-%m-%d %H:%M:%S}）")
        missing = [cid for cid in cross_ids if str(cid) not in data]
        if missing:
            print(f"  其中未收录: {missing[:10]}")
    else:
        print(f"\n经验表不存在: {table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
