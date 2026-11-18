"""新增路口自动配置工具。

校验 cross_info、road_info 后，把新路口写入：
  1. Lambdas.config_lambda 的所有数据源列表
  2. Lambdas.intersection_list
  3. Lambdas.location_to_intersection_lambda（摄像头/设备号 -> (路口, 方向)）
  4. lib/DQN_Select.py 的 Cross_Video 字典
  5. lib/intersection_strategy.py 的平台相位策略清单
  6. lib/Global_intersection_coordinate.py 的 video_flow_road 集合
  7. lib/plan_id_overrides.json 的平台默认方案号

新增路口共用配时入口，试点和学习范围从策略清单自动包含，不克隆业务函数。

用法：
  python tools/onboard_intersection.py --cross 999999
  python tools/onboard_intersection.py --cross 999999 --apply
"""

from __future__ import annotations

import argparse
import ast
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib._local_json_store import read_json_object, write_json_object
from lib.control_functions.global_processors.phase_adapter import phase_bounds
from lib.cross_info_functions import _normalize_cross_info
from lib.data_ANS.phase_definitions import PHASE_DIRECTION_MAP
from tools.control_config_audit import _cycle_equal


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
        default = program_id if program_id is not None else overrides.get(cross_id, min(programs))
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


def _find_assign(tree: ast.Module, name: str) -> ast.Assign:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node
    raise ValueError(f"未找到赋值: {name}")


def _container(assign: ast.Assign) -> ast.AST:
    value = assign.value
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Attribute):
            return value.func.value
        if isinstance(value.func, ast.Name) and value.args:
            inner = value.args[0]
            if isinstance(inner, (ast.Set, ast.List, ast.Tuple, ast.Dict)):
                return inner
    return value


def _leading_indent(lines: list[str], lineno: int) -> str:
    line = lines[lineno - 1]
    return line[: len(line) - len(line.lstrip())]


def _insert_lines(text: str, node: ast.AST, new_lines: list[str]) -> str:
    lines = text.splitlines()
    closing_index = node.end_lineno - 1
    indent = _leading_indent(lines, closing_index)
    if getattr(node, "elts", None):
        indent = _leading_indent(lines, node.elts[0].lineno)
    elif getattr(node, "keys", None):
        indent = _leading_indent(lines, node.keys[0].lineno)
    lines[closing_index:closing_index] = [indent + item for item in new_lines]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _literal(node: ast.AST):
    return ast.literal_eval(node)


def _insert_config_lambda(text: str, cross_ids: list[str]) -> tuple[str, list[str]]:
    changes = []
    for cross_id in cross_ids:
        tree = ast.parse(text)
        assign = _find_assign(tree, "config_lambda")
        keys = [key.value for key in _container(assign).keys]
        for index, key in enumerate(keys):
            # 每次插入后行号会变化，重新解析再定位
            tree = ast.parse(text)
            assign = _find_assign(tree, "config_lambda")
            list_node = _container(assign).values[index]
            current = {str(_literal(item)) for item in list_node.elts}
            if cross_id in current:
                continue
            text = _insert_lines(text, list_node, [f"'{cross_id}',"])
            changes.append(f"config_lambda[{key}] += {cross_id}")
    return text, changes


def _insert_intersection_list(text: str, cross_ids: list[str]) -> tuple[str, list[str]]:
    changes = []
    for cross_id in cross_ids:
        tree = ast.parse(text)
        assign = _find_assign(tree, "intersection_list")
        node = _container(assign)
        current = {str(_literal(item)) for item in node.elts}
        if cross_id in current:
            continue
        text = _insert_lines(text, node, [f"'{cross_id}',"])
        changes.append(f"intersection_list += {cross_id}")
    return text, changes


def _insert_location_map(text: str, entries: dict[str, dict]) -> tuple[str, list[str]]:
    tree = ast.parse(text)
    assign = _find_assign(tree, "location_to_intersection_lambda")
    existing = ast.literal_eval(_container(assign))
    aliases = ast.literal_eval(_container(_find_assign(tree, "aibi_to_xinkongji")))
    changes = []
    for cross_id, entry in entries.items():
        lines = []
        for location_id, direction in sorted(entry["jtll_ddbh"].items()):
            detector_id = int(location_id)
            if detector_id in existing:
                owner, mapped_direction = existing[detector_id]
                if (str(aliases.get(str(owner), owner)), mapped_direction) != (cross_id, direction):
                    raise ValueError(f"检测器 {detector_id} 已映射至 {owner}/{mapped_direction}，"
                                     f"与路口 {cross_id}/{direction} 冲突")
                continue
            existing[detector_id] = (cross_id, direction)
            lines.append(f"{detector_id}: ('{cross_id}', '{direction}'),")
        if not lines:
            continue
        text = _insert_lines(text, _container(assign), lines)
        changes.append(f"location_to_intersection_lambda += {cross_id}")
    return text, changes


def _insert_cross_video(text: str, cross_ids: list[str]) -> tuple[str, list[str]]:
    changes = []
    for cross_id in cross_ids:
        tree = ast.parse(text)
        assign = _find_assign(tree, "Cross_Video")
        node = _container(assign)
        existing = {str(_literal(key)) for key in node.keys}
        if cross_id in existing:
            continue
        text = _insert_lines(
            text, node, [f"'{cross_id}': {{\"Cross_type\": \"Video\"}},"]
        )
        changes.append(f"Cross_Video += {cross_id}")
    return text, changes


def _insert_set(text: str, var_name: str, cross_ids: list[str]) -> tuple[str, list[str]]:
    changes = []
    for cross_id in cross_ids:
        tree = ast.parse(text)
        assign = _find_assign(tree, var_name)
        node = _container(assign)
        existing = {str(_literal(item)) for item in node.elts}
        if cross_id in existing:
            continue
        text = _insert_lines(text, node, [f"{cross_id},"])
        changes.append(f"{var_name} += {cross_id}")
    return text, changes


def _insert_str_set(text: str, var_name: str, cross_ids: list[str]) -> tuple[str, list[str]]:
    changes = []
    for cross_id in cross_ids:
        tree = ast.parse(text)
        assign = _find_assign(tree, var_name)
        node = _container(assign)
        existing = {str(_literal(item)) for item in node.elts}
        if cross_id in existing:
            continue
        text = _insert_lines(text, node, [f"'{cross_id}',"])
        changes.append(f"{var_name} += {cross_id}")
    return text, changes


def plan_edits(root: Path, cross_entries: dict[str, dict]) -> dict[str, tuple[str, list[str]]]:
    cross_ids = sorted(cross_entries)

    lambdas_path = root / "Lambdas.py"
    lambdas_text = lambdas_path.read_text(encoding="utf-8-sig")
    lambdas_text, c1 = _insert_config_lambda(lambdas_text, cross_ids)
    lambdas_text, c2 = _insert_intersection_list(lambdas_text, cross_ids)
    lambdas_text, c3 = _insert_location_map(lambdas_text, cross_entries)

    dqn_path = root / "lib/DQN_Select.py"
    dqn_text = dqn_path.read_text(encoding="utf-8-sig")
    dqn_text, c4 = _insert_cross_video(dqn_text, cross_ids)
    strategy_path = root / "lib/intersection_strategy.py"
    strategy_text = strategy_path.read_text(encoding="utf-8-sig")
    strategy_text, c5 = _insert_str_set(strategy_text, "PLATFORM_PHASE_ROAD_IDS", cross_ids)

    coord_path = root / "lib/Global_intersection_coordinate.py"
    coord_text = coord_path.read_text(encoding="utf-8-sig")
    coord_text, c7 = _insert_set(coord_text, "video_flow_road", cross_ids)

    return {
        str(lambdas_path): (lambdas_text, c1 + c2 + c3),
        str(dqn_path): (dqn_text, c4),
        str(strategy_path): (strategy_text, c5),
        str(coord_path): (coord_text, c7),
    }


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
        overrides = read_json_object(overrides_path)
        program_ids, warnings = _validate_programs(
            cross_entries, read_json_object(root / "lib" / "road_info.json"), overrides, args.program_id,
        )
        edits = plan_edits(root, cross_entries)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    for warning in warnings:
        print(f"[核对] {warning}")
    print(f"默认方案号：{program_ids}")

    changed_files = 0
    for path, (new_text, changes) in edits.items():
        old_text = Path(path).read_text(encoding="utf-8-sig")
        if not changes:
            print(f"[skip] {path}: 无变化")
            continue
        changed_files += 1
        print(f"[plan] {path}")
        for item in changes:
            print("  -", item)
        if args.apply:
            Path(path).write_text(new_text, encoding="utf-8")
        else:
            diff = difflib.unified_diff(
                old_text.splitlines(), new_text.splitlines(),
                fromfile=path, tofile=path + " (new)", lineterm="",
            )
            print("\n".join(list(diff)[:80]))

    if args.apply and any(overrides.get(road) != state for road, state in program_ids.items()):
        overrides.update(program_ids)
        write_json_object(overrides_path, overrides)
        print(f"方案号已写入 {overrides_path}")

    if args.apply and changed_files:
        print("已写入；请完成编译与回归后按 PR 流程提交。打包另行决定。")
        print(
            "提示：如目标部署设置了 AITC_FLOW_ALLOCATOR_PILOT_ROADS，"
            "需要把新路口追加进该环境变量，否则在线学习分配器不会接管。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
