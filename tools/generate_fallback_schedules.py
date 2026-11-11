"""为缺少时段方案的路口生成兜底方案。

输入 lib/road_info.json 的 state "0"（相位最小放行），生成 24 小时的
Time_schedule_<cross>.json 与 Time_schedule_weekend_<cross>.json，
并更新 time_schedule/schedule_json/time_schedule_manifest.json。

用法：
  python tools/generate_fallback_schedules.py --dry-run
  python tools/generate_fallback_schedules.py --apply
  python tools/generate_fallback_schedules.py --cross 1700062 --apply
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _fallback_vector(state_config: dict, length: int = 10) -> list[int]:
    phases = state_config.get("phase") or []
    minimums = state_config.get("min_pass_time") or []
    platform = state_config.get("platform_min_pass_time") or []
    maximums = state_config.get("max_pass_time") or []

    vector = [0] * length
    for index in range(min(length, len(phases))):
        if not phases[index]:
            continue
        low = max(
            int(minimums[index]) if index < len(minimums) else 0,
            int(platform[index]) if index < len(platform) else 0,
        )
        high = int(maximums[index]) if index < len(maximums) else 0
        if high > 0:
            low = min(low, high)
        vector[index] = max(low, 0)
    return vector


def _schedule(vector: list[int]) -> dict[str, list[int]]:
    return {str(hour): list(vector) for hour in range(24)}


def generate(root: Path, cross_ids: list[str] | None, apply: bool) -> int:
    road_info_path = root / "lib" / "road_info.json"
    schedule_dir = root / "time_schedule" / "schedule_json"
    manifest_path = schedule_dir / "time_schedule_manifest.json"

    road_info = _load(road_info_path)
    manifest = _load(manifest_path)

    candidates = sorted(road_info)
    if cross_ids:
        missing = [cid for cid in cross_ids if cid not in road_info]
        if missing:
            raise SystemExit(f"road_info 中不存在: {missing}")
        candidates = sorted(set(cross_ids))

    created = 0
    updated_items = 0
    for cross_id in candidates:
        workday = schedule_dir / f"Time_schedule_{cross_id}.json"
        weekend = schedule_dir / f"Time_schedule_weekend_{cross_id}.json"
        if workday.exists() and weekend.exists():
            continue

        states = road_info[cross_id]
        state_key = "0" if "0" in states else sorted(states)[0]
        state_config = states.get(state_key)
        if not isinstance(state_config, dict):
            print(f"[skip] {cross_id}: road_info 缺少可用状态")
            continue

        vector = _fallback_vector(state_config)
        payload = _schedule(vector)
        print(f"[plan] {cross_id} state={state_key}: {vector[:8]}")
        created += 1
        if not apply:
            continue

        schedule_dir.mkdir(parents=True, exist_ok=True)
        workday.write_text(
            json.dumps(payload, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )
        weekend.write_text(
            json.dumps(payload, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )

        item = manifest["items"].get(cross_id)
        if item is None:
            manifest["items"][cross_id] = {
                "data_id": f"time_schedule_{cross_id}.json",
                "version": 1,
            }
            updated_items += 1

    if apply and (created or updated_items):
        manifest["version"] = int(manifest.get("version", 1)) + 1
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"已生成 {created} 个路口的兜底方案，manifest 新增 {updated_items} 项，"
            f"版本 {manifest['version']}"
        )
    else:
        print(f"计划生成 {created} 个路口，manifest 新增 {updated_items} 项")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成路口兜底时段方案")
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument("--cross", action="append", default=None, help="只处理指定路口")
    parser.add_argument("--apply", action="store_true", help="写入文件（默认预览）")
    args = parser.parse_args(argv)
    return generate(Path(args.root).resolve(), args.cross, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
