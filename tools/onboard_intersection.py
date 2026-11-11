"""新增路口自动配置工具。

按一个 spec（cross_info 中的 jtll_ddbh）把新路口写入：
  1. Lambdas.config_lambda 的所有数据源列表
  2. Lambdas.intersection_list
  3. Lambdas.location_to_intersection_lambda（摄像头/设备号 -> (路口, 方向)）
  4. lib/DQN_Select.py 的 Cross_Video 字典
  5. lib/DQN_Select.py 的 if cross_id in Cross_Video 分发分支
  6. lib/DQN_Select.py 的 DQN_select_<id> 函数（从模板克隆）
  7. lib/Global_intersection_coordinate.py 的 video_flow_road 集合
  8. lib/data_ANS/flow_allocator_shadow.py 的 DEFAULT_TARGET_ROAD_IDS（在线学习试点集合）

用法：
  python tools/onboard_intersection.py --cross 999999 --dry-run
  python tools/onboard_intersection.py --cross 999999 --apply
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
from pathlib import Path


def _load_cross_entries(path: Path, cross_ids: list[str]) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = {}
    for cross_id in cross_ids:
        entry = data.get(cross_id)
        if not isinstance(entry, dict):
            raise ValueError(f"cross_info.json 中不存在路口: {cross_id}")
        jtll = entry.get("jtll_ddbh")
        if not isinstance(jtll, dict) or not jtll:
            raise ValueError(f"路口 {cross_id} 缺少 jtll_ddbh")
        entries[cross_id] = {"jtll_ddbh": {str(k): str(v) for k, v in jtll.items()}}
    return entries


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


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise ValueError(f"未找到函数: {name}")


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
    existing = {
        str(_literal(key)) for key in _container(assign).keys
    }
    changes = []
    for cross_id, entry in entries.items():
        lines = []
        for location_id, direction in sorted(entry["jtll_ddbh"].items()):
            if location_id in existing:
                continue
            lines.append(f"{location_id}: ('{cross_id}', '{direction}'),")
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


def _insert_dispatcher(text: str, cross_ids: list[str], template: str) -> tuple[str, list[str]]:
    tree = ast.parse(text)
    func = _find_function(tree, "DQN_select")
    target = None
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "cross_id"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.In)
            and isinstance(test.comparators[0], ast.Name)
            and test.comparators[0].id == "Cross_Video"
            and node.body
        ):
            target = node
            break
    if target is None:
        raise ValueError("未找到 if cross_id in Cross_Video 分支")

    changes = []
    pending = [
        cross_id for cross_id in cross_ids
        if f"cross_id == '{cross_id}'" not in text
    ]
    if not pending:
        return text, changes

    lines = text.splitlines()
    insert_at = target.body[0].lineno - 1
    indent = _leading_indent(lines, target.body[0].lineno)
    block = []
    for cross_id in pending:
        block.extend([
            f"{indent}if cross_id == '{cross_id}':",
            f"{indent}    return DQN_select_{cross_id}(",
            f"{indent}        traffic_vector,",
            f"{indent}        queue_vector,",
            f"{indent}        traffic_vector_duration2,",
            f"{indent}        current_time,",
            f"{indent}        flow_map_single_intersection,",
            f"{indent}        queue_map_single_intersection,",
            f"{indent}        stage_map_single_intersection,",
            f"{indent}        extend_map_single_intersection,",
            f"{indent}        0,",
            f"{indent}        cur_flow_pre_map,",
            f"{indent}        cur_queue_pre_map,",
            f"{indent}    )",
        ])
        changes.append(f"dispatcher += {cross_id}")
    lines[insert_at:insert_at] = block
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), changes


def _append_function(text: str, cross_ids: list[str], template_id: str) -> tuple[str, list[str]]:
    tree = ast.parse(text)
    template = _find_function(tree, f"DQN_select_{template_id}")
    lines = text.splitlines()
    source = "\n".join(lines[template.lineno - 1: template.end_lineno])

    changes = []
    for cross_id in cross_ids:
        if f"def DQN_select_{cross_id}(" in text:
            continue
        body = re.sub(
            rf"(?<!\d){re.escape(template_id)}(?!\d)", cross_id, source
        )
        text = text.rstrip() + "\n\n\n" + body + "\n"
        changes.append(f"DQN_select_{cross_id} 克隆自 {template_id}")
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


def plan_edits(root: Path, cross_entries: dict[str, dict], template: str) -> dict[str, tuple[str, list[str]]]:
    cross_ids = sorted(cross_entries)

    lambdas_path = root / "Lambdas.py"
    lambdas_text = lambdas_path.read_text(encoding="utf-8-sig")
    lambdas_text, c1 = _insert_config_lambda(lambdas_text, cross_ids)
    lambdas_text, c2 = _insert_intersection_list(lambdas_text, cross_ids)
    lambdas_text, c3 = _insert_location_map(lambdas_text, cross_entries)

    dqn_path = root / "lib/DQN_Select.py"
    dqn_text = dqn_path.read_text(encoding="utf-8-sig")
    dqn_text, c4 = _insert_cross_video(dqn_text, cross_ids)
    dqn_text, c5 = _insert_dispatcher(dqn_text, cross_ids, template)
    dqn_text, c6 = _append_function(dqn_text, cross_ids, template)

    coord_path = root / "lib/Global_intersection_coordinate.py"
    coord_text = coord_path.read_text(encoding="utf-8-sig")
    coord_text, c7 = _insert_set(coord_text, "video_flow_road", cross_ids)

    shadow_path = root / "lib/data_ANS/flow_allocator_shadow.py"
    shadow_text = shadow_path.read_text(encoding="utf-8-sig")
    shadow_text, c8 = _insert_str_set(
        shadow_text, "DEFAULT_TARGET_ROAD_IDS", cross_ids
    )

    experience_path = root / "lib/data_ANS/experience_runtime.py"
    experience_text = experience_path.read_text(encoding="utf-8-sig")
    experience_text, c9 = _insert_str_set(
        experience_text, "DEFAULT_POOL_COLLECTION_ROAD_IDS", cross_ids
    )
    experience_text, c10 = _insert_str_set(
        experience_text, "DEFAULT_TABLE_UPDATE_ROAD_IDS", cross_ids
    )

    return {
        str(lambdas_path): (lambdas_text, c1 + c2 + c3),
        str(dqn_path): (dqn_text, c4 + c5 + c6),
        str(coord_path): (coord_text, c7),
        str(shadow_path): (shadow_text, c8),
        str(experience_path): (experience_text, c9 + c10),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="新增路口自动配置")
    parser.add_argument("--cross", action="append", required=True, help="新增路口 ID，可重复")
    parser.add_argument("--cross-info", default="lib/cross_info.json",
                        help="包含新路口配置的 cross_info.json")
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument("--template", default="2272",
                        help="用于克隆 DQN 函数的现有路口（默认 2272，走在线学习分配器）")
    parser.add_argument("--apply", action="store_true", help="写入文件（默认只预览）")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    cross_entries = _load_cross_entries(root / args.cross_info, args.cross)
    template_text = (root / "lib/DQN_Select.py").read_text(encoding="utf-8-sig")
    if f"def DQN_select_{args.template}(" in template_text and (
        "select_pilot_schedule" not in template_text.split(
            f"def DQN_select_{args.template}(", 1
        )[1].split("\ndef ", 1)[0]
    ):
        print(
            f"警告：模板 {args.template} 不使用在线学习分配器，"
            "新路口将依赖 offline_experience 经验表；免训练上线请用默认模板 2272。"
        )
    edits = plan_edits(root, cross_entries, args.template)

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

    if args.apply and changed_files:
        print("已写入；请执行 python -m py_compile 与测试后重新打包。")
        print(
            "提示：如目标部署设置了 AITC_FLOW_ALLOCATOR_PILOT_ROADS，"
            "需要把新路口追加进该环境变量，否则在线学习分配器不会接管。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
