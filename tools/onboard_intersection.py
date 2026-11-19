"""校验 cross_info 和 road_info，为新路口写入一条平台方案登记。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib._local_json_store import read_json_object, write_json_object
from lib.control_functions.global_processors.phase_adapter import phase_bounds
from lib.cross_info_functions import _normalize_cross_info
from lib.data_ANS.phase_definitions import PHASE_DIRECTION_MAP
from lib.intersection_strategy import PLATFORM_PHASE_ROAD_IDS
from lib.platform_registration import platform_additions, registered_platform_programs
from tools.control_config_audit import _cycle_equal, bindings


def _load_cross_entries(path: Path, cross_ids: list[str]) -> dict[str, dict]:
    data = read_json_object(path)
    entries = {}
    for cross_id in cross_ids:
        if not cross_id.isdigit():
            raise ValueError(f"无效路口编号 {cross_id}")
        if cross_id not in data:
            raise ValueError(f"cross_info.json 中不存在路口 {cross_id}")
        try:
            entries[cross_id] = _normalize_cross_info({"cross_info": data[cross_id]})
        except ValueError as error:
            raise ValueError(f"路口 {cross_id} {error}") from error
    return entries


def _phase_signature(phases):
    return [tuple(sorted(PHASE_DIRECTION_MAP.get(str(phase).upper(), ()))) for phase in phases]


def _validate_programs(cross_entries, road_info, overrides, program_id):
    selected = {}
    warnings = []
    for cross_id, cross in cross_entries.items():
        programs = road_info.get(cross_id)
        if not isinstance(programs, dict) or not programs:
            raise ValueError(f"road_info.json 中缺少路口 {cross_id} 的方案")
        existing = overrides.get(cross_id, min(programs))
        if isinstance(existing, dict):
            existing = existing["program_id"]
        default = program_id if program_id is not None else existing
        try:
            default = int(default)
        except (TypeError, ValueError) as error:
            raise ValueError(f"路口 {cross_id} 默认方案号 {default!r} 无效") from error
        if str(default) not in programs:
            raise ValueError(f"路口 {cross_id} 默认方案 {default} 不在 road_info 中")

        signatures = []
        for state, config in programs.items():
            if not isinstance(config, dict) or not isinstance(config.get("phase"), list):
                raise ValueError(f"路口 {cross_id} 方案 {state} 缺少有效的相位列表")
            try:
                phases, _, _ = phase_bounds(config)
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"路口 {cross_id} 方案 {state} 的相位或时长无效：{error}") from error
            signatures.append(_phase_signature(phases))

        cycles = cross.get("Cycle", [])
        if not cycles:
            warnings.append(f"路口 {cross_id} 缺少 Cycle，在线学习暂时无法识别完整周期")
        for cycle in cycles:
            try:
                signature = _phase_signature([cross["phase"][str(stage)] for stage in cycle])
            except KeyError as error:
                raise ValueError(f"路口 {cross_id} 周期 {cycle} 引用了未定义的阶段 {error}") from error
            if not any(_cycle_equal(signature, candidate) for candidate in signatures):
                warnings.append(f"路口 {cross_id} 周期 {cycle} 的方向顺序未匹配方案，需核对现场阶段配置")
        selected[cross_id] = default
    return selected, warnings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="新增路口自动配置")
    parser.add_argument("--cross", action="append", required=True, help="新增路口 ID，可重复")
    parser.add_argument("--cross-info", default="lib/cross_info.json",
                        help="包含新路口配置的 cross_info.json")
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument("--template", default="2272",
                        help="兼容旧命令；新路口已使用统一在线入口，不再克隆模板")
    parser.add_argument("--apply", action="store_true", help="写入文件（默认只预览）")
    parser.add_argument("--program-id", type=int,
                        help="平台默认方案号。省略时沿用已有登记，首次取 road_info 第一个状态键")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.template != "2272":
        parser.error("新路口已使用统一在线入口，不再支持克隆其他路口模板")
    overrides_path = root / "lib" / "plan_id_overrides.json"
    try:
        cross_entries = _load_cross_entries(root / args.cross_info, args.cross)
        crosses = read_json_object(root / "lib" / "cross_info.json")
        road_info = read_json_object(root / "lib" / "road_info.json")
        overrides = read_json_object(overrides_path)
        program_ids, warnings = _validate_programs(cross_entries, road_info, overrides, args.program_id)
        runtime = bindings(
            root / "Lambdas.py",
            {"intersection_list", "location_to_intersection_lambda", "aibi_to_xinkongji"},
        )
        legacy_roads = set(runtime["intersection_list"]) - PLATFORM_PHASE_ROAD_IDS
        if legacy_roads & program_ids.keys():
            raise ValueError(f"已上线的旧路口应单独迁移配时策略: {sorted(legacy_roads & program_ids.keys())}")

        if args.apply:
            active = _load_cross_entries(root / "lib" / "cross_info.json", args.cross)
            if active != cross_entries:
                raise ValueError("--cross-info 与实际运行的 lib/cross_info.json 不一致，请先同步")
        prospective = {**registered_platform_programs(overrides), **program_ids}
        _, issues = platform_additions(
            prospective, runtime["intersection_list"], {**crosses, **cross_entries},
            road_info, runtime["location_to_intersection_lambda"], runtime["aibi_to_xinkongji"],
        )
        if issues:
            raise ValueError("；".join(f"路口 {road} {problem}" for road, problem in issues.items()))
    except (OSError, ValueError) as error:
        parser.error(str(error))

    for warning in warnings:
        print(f"[核对] {warning}")
    updated = dict(overrides)
    for road, program in sorted(program_ids.items()):
        # 已上线的数字型配置只更新默认方案，新增路口使用显式接入登记。
        updated[road] = program if road in runtime["intersection_list"] else {"program_id": program}
        print(f"[登记] {road} 默认方案 {program}")
    if updated == overrides:
        print("登记无变化")
    elif args.apply:
        write_json_object(overrides_path, updated)
        print(f"已写入 {overrides_path}，请按 PR 流程提交，登记在服务启动时读取。")
    else:
        print(f"预览 {overrides_path}，使用 --apply 写入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
