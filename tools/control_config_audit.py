"""只读核对三类路口的调用入口、路由和相位配置；不导入或执行生产模块。"""

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_KEYS = {"AITC_FLOW_ALLOCATOR_PILOT_MODE", "AITC_FLOW_ALLOCATOR_PILOT_ROADS",
            "AITC_FLOW_ALLOCATOR_SHADOW_ROADS", "AITC_FLOW_ALLOCATOR_SHADOW_ENABLED",
            "AITC_FLOW_ALLOCATOR_SHADOW_TABLE", "AITC_FLOW_ALLOCATOR_SHADOW_CROSS_INFO",
            "AITC_DATA_ROOT"}


def _literal(node, known):
    """仅解析字面量和容器包装，遇到计算或动态表达式明确失败。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in known:
        return known[node.id]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [_literal(item, known) for item in node.elts]
        return (tuple(values) if isinstance(node, ast.Tuple) else
                set(values) if isinstance(node, ast.Set) else values)
    if isinstance(node, ast.Dict):
        result = {}
        for key, value in zip(node.keys, node.values):
            if key is None:
                result.update(_literal(value, known))
            else:
                result[_literal(key, known)] = _literal(value, known)
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_literal(node.operand, known)
    if isinstance(node, ast.Call) and not node.keywords:
        if isinstance(node.func, ast.Name) and node.func.id in ("frozenset", "set", "tuple", "list"):
            return {"frozenset": frozenset, "set": set, "tuple": tuple, "list": list}[node.func.id](
                _literal(node.args[0], known) if node.args else ())
        if isinstance(node.func, ast.Attribute) and node.func.attr == "copy" and not node.args:
            return _literal(node.func.value, known).copy()
    raise ValueError(f"不能静态解析第 {getattr(node, 'lineno', '?')} 行的 {type(node).__name__}")


def bindings(path, names, known=None, *, source=None):
    values = dict(known or {})
    tree = ast.parse(source.decode("utf-8-sig") if source is not None else path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in names:
                    values[target.id] = _literal(node.value, values)
    missing = set(names) - values.keys()
    if missing:
        raise ValueError(f"{path.name} 缺少静态定义: {sorted(missing)}")
    return {name: values[name] for name in names}


def _read_json(path, source):
    value = json.loads(source.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 顶层必须为对象")
    return value


def _environment(root, overrides):
    # 只读取与试点路由有关的白名单，报告不包含其他环境变量或凭据。
    values = {}
    path = root / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = raw.strip().partition("=")
            if separator and key.strip() in ENV_KEYS:
                # 与app.config._load_dotenv一致：首值优先，不识别export前缀。
                value = value.strip()
                if value[:1] in {'"', "'"}:
                    end = value.find(value[0], 1)
                    value = value[1:] if end == -1 else value[1:end]
                else:
                    value = value.split(" #", 1)[0].strip()
                values.setdefault(key.strip(), value)
    values.update({k: str(v) for k, v in overrides.items() if k in ENV_KEYS})
    return values


def _calls(function):
    return sorted({node.func.id for node in ast.walk(function)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)})


def _selectors(path, source):
    tree = ast.parse(source.decode("utf-8-sig"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    dispatcher = functions["DQN_select"]
    routes = {}
    for node in ast.walk(dispatcher):
        if not isinstance(node, ast.If):
            continue
        ids = []
        for test in ast.walk(node.test):
            if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
                operands = [test.left, *test.comparators]
                if any(isinstance(x, ast.Name) and x.id == "cross_id" for x in operands):
                    ids.extend(str(x.value) for x in operands if isinstance(x, ast.Constant))
        if not ids:
            continue
        calls = _calls(ast.Module(body=node.body, type_ignores=[]))
        targets = [name for name in calls if name.startswith("DQN_select_")]
        for rid in ids:
            routes[rid] = {"dispatcher_line": node.lineno,
                           "functions": targets, "direct_calls": calls if not targets else []}
    return functions, routes


def _pilot_call_roads(function):
    # 当前选择器显式传入路口ID；动态参数无法确认时不冒充已正确接线。
    known, roads = {}, set()
    for node in function.body:
        if isinstance(node, ast.Assign):
            try:
                value = _literal(node.value, known)
            except ValueError:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    known[target.id] = value
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "select_pilot_schedule":
            argument = node.args[0] if node.args else next((x.value for x in node.keywords if x.arg == "cross_id"), None)
            try:
                roads.add(str(_literal(argument, known)))
            except ValueError:
                roads.add(None)
    return roads


def _normalized_state(value):
    # 与road_state._normalize_state_key一致，保持审计工具不导入生产模块。
    if isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    try:
        return str(int(value))
    except (TypeError, ValueError, OverflowError):
        return str(value).strip()


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _cycle_equal(left, right):
    return len(left) == len(right) and any(left == right[i:]+right[:i] for i in range(len(right)))


def audit(root=ROOT, *, roads=None, group="all", environ=None):
    root = Path(root).resolve()
    sources = ["Lambdas.py", "lib/DQN_Select.py", "lib/road_groups.py",
               "lib/Global_intersection_coordinate.py", "lib/data_ANS/flow_allocator_shadow.py",
               "lib/data_ANS/lane_policy.py", "lib/data_ANS/cycle_quality.py",
               "lib/control_functions/global_processors/phase_adapter.py", "lib/road_info.json",
               "lib/cross_info.json", "lib/road_state.json", "lib/plan_id_overrides.json"]
    snapshot = {path: (root/path).read_bytes() for path in sources}
    def static(path, names, known=None):
        return bindings(root/path, names, known, source=snapshot[path])
    runtime = static("Lambdas.py", {"intersection_list", "location_to_intersection_lambda",
                                          "flow_map_single_intersection_lambda", "aibi_to_xinkongji"})
    groups = static("lib/road_groups.py", {"TONGZHOU_19", "TONGZHOU_49"})
    old, new = set(groups["TONGZHOU_19"]), set(groups["TONGZHOU_49"])
    if old & new:
        raise ValueError("19组与49组清单存在重叠")
    registry = list(map(str, runtime["intersection_list"]))
    registered = set(registry)
    coordination = static("lib/Global_intersection_coordinate.py",
                            {"intern_road_id", "video_road", "video_flow_road"})
    pilot = static("lib/data_ANS/flow_allocator_shadow.py",
                     {"DEFAULT_TARGET_ROAD_IDS", "DEFAULT_PILOT_MODE"})
    lane = static("lib/data_ANS/lane_policy.py", {"LANE_TYPE_RULES", "DEDICATED_LEFT_TURN_LANE_TYPE"})
    training = static("lib/data_ANS/cycle_quality.py", {"PHASE_DIRECTION_MAP"})["PHASE_DIRECTION_MAP"]
    movements = static("lib/control_functions/global_processors/phase_adapter.py",
                         {"PHASE_DIRECTION_MAP"}, {"TRAINING_PHASE_DIRECTION_MAP": training})["PHASE_DIRECTION_MAP"]
    road_info = _read_json(root/"lib/road_info.json", snapshot["lib/road_info.json"])
    cross_info = _read_json(root/"lib/cross_info.json", snapshot["lib/cross_info.json"])
    forced = _read_json(root/"lib/road_state.json", snapshot["lib/road_state.json"])
    overrides = _read_json(root/"lib/plan_id_overrides.json", snapshot["lib/plan_id_overrides.json"])
    functions, routes = _selectors(root/"lib/DQN_Select.py", snapshot["lib/DQN_Select.py"])
    video_registry = static("lib/DQN_Select.py", {"Cross_Video"})["Cross_Video"]
    env = _environment(root, os.environ if environ is None else environ)
    mode = env.get("AITC_FLOW_ALLOCATOR_PILOT_MODE", pilot["DEFAULT_PILOT_MODE"]).strip().lower()
    invalid_mode = mode not in {"new", "shadow", "legacy"}
    if invalid_mode:
        mode = "legacy"
    selected = env.get("AITC_FLOW_ALLOCATOR_PILOT_ROADS", "").strip() or env.get("AITC_FLOW_ALLOCATOR_SHADOW_ROADS", "").strip()
    pilot_roads = {x.strip() for x in selected.split(",") if x.strip()} if selected else set(pilot["DEFAULT_TARGET_ROAD_IDS"])
    enabled = env.get("AITC_FLOW_ALLOCATOR_SHADOW_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    def batch(rid):
        return "19" if rid in old else "49" if rid in new else "historical"
    universe = set(roads) if roads is not None else registered | old | new
    selected_roads = sorted(r for r in universe if group == "all" or batch(r) == group)
    findings, inventory = [], []
    def issue(rid, code, message, *, severity="warning", state=None):
        findings.append({"road_id": rid, "group": batch(rid), "severity": severity,
                         "code": code, "state": state, "message": message})
    detector_owners = defaultdict(set)
    for rid, cross in cross_info.items():
        if rid in registered | old | new and isinstance(cross, dict):
            detectors = cross.get("jtll_ddbh", {})
            if isinstance(detectors, dict):
                for detector in detectors:
                    detector_owners[str(detector)].add(rid)
    for rid in selected_roads:
        route = routes.get(rid, {})
        targets = route.get("functions", [])
        calls = sorted({call for name in targets if name in functions for call in _calls(functions[name])})
        pilot_call_roads = set().union(*(_pilot_call_roads(functions[name]) for name in targets if name in functions))
        wired = rid in pilot_call_roads
        online_eligible = wired and rid in registered and rid in video_registry and rid in pilot_roads and enabled and mode == "new"
        if None in pilot_call_roads:
            issue(rid, "unresolved_pilot_road", "在线候选的路口参数无法静态解析，不能确认接线")
        if pilot_call_roads - {rid, None}:
            issue(rid, "pilot_road_mismatch", f"在线候选实际传入路口 {sorted(pilot_call_roads - {None})}，与分派路口不一致", severity="error")
        categories = [name for name, values in coordination.items() if rid in set(map(str, values))]
        inventory.append({"road_id": rid, "group": batch(rid), "registered": rid in registered,
                          "dispatcher_line": route.get("dispatcher_line"), "selector_functions": targets,
                          "selector_calls": calls, "direct_dispatch_calls": route.get("direct_calls", []),
                          "legacy_experience_lookup": bool({"chuli_shuju", "chuli_shuju3"} & set(calls)),
                          "pilot_wired": wired, "pilot_call_road_ids": sorted(pilot_call_roads, key=str), "pilot_target": rid in pilot_roads,
                          "configured_pilot_mode": mode, "online_candidate_eligible": online_eligible,
                          "selector_entry": ("not_registered" if rid not in registered else
                                             "dedicated_function" if targets else
                                             "generic_timetable_candidate" if rid in video_registry else
                                             "generic_zero_candidate"),
                          "legacy_computation_precedes_pilot": wired and bool({"chuli_shuju", "chuli_shuju3"} & set(calls)),
                          "coordination_categories": categories,
                          "phase_adapter": "bounded_movement_adapter" if rid in new and "video_flow_road" in categories else "existing_category_rules",
                          "program_ids": list(road_info.get(rid, {})) if isinstance(road_info.get(rid), dict) else []})
        if rid not in registered:
            issue(rid, "not_registered", "上线清单中存在，但未注册到 intersection_list；需确认是否计划启用")
        for target in targets:
            if target not in functions:
                issue(rid, "missing_selector_function", f"分派目标 {target} 未定义", severity="error")
        if len(categories) > 1:
            issue(rid, "multiple_coordination_categories", f"同时属于 {categories}，需保留协调覆盖顺序")
        if wired and (rid not in pilot_roads or not enabled or mode != "new"):
            issue(rid, "online_candidate_not_selected", "虽然已接线到试点，但当前配置不会选用在线候选", severity="info")
        cross = cross_info.get(rid)
        cross_present = isinstance(cross, dict)
        if not cross_present:
            issue(rid, "missing_cross_info", "缺少 cross_info，经验统计与车道映射无法核对")
            cross = {}
        def cross_field(name, expected_type, required=True):
            if required and cross_present and name not in cross:
                issue(rid, "missing_cross_field", f"cross_info缺少必需字段{name}", severity="error")
            value = cross.get(name, expected_type())
            if not isinstance(value, expected_type):
                issue(rid, "invalid_cross_field", f"cross_info.{name} 结构无效", severity="error")
                return expected_type()
            return value
        expected = set()
        for direction, lanes in cross_field("LaneNo", dict).items():
            if not isinstance(lanes, dict):
                issue(rid, "invalid_lane_map", f"{direction} 车道配置不是对象", severity="error")
                continue
            capacity = len(runtime["flow_map_single_intersection_lambda"]["pass"].get(direction, []))
            for key, kind in lanes.items():
                try:
                    index = int(key)
                    if index < 0:
                        raise ValueError()
                except (TypeError, ValueError):
                    issue(rid, "invalid_lane_index", f"{direction} 车道号 {key} 无效", severity="error")
                    continue
                if index >= capacity:
                    issue(rid, "lane_outside_runtime_vector", f"{direction}:{key} 超出实时向量索引范围 0..{capacity-1}，对应原始记录会被拒绝")
                rule = lane["LANE_TYPE_RULES"].get(str(kind).strip().upper())
                if rule is None:
                    issue(rid, "unknown_lane_type", f"{direction}:{key} 的车道类型 {kind} 未定义")
                elif rule["capacity_eligible"]:
                    expected.add(direction + "TL" if str(kind).strip().upper() == lane["DEDICATED_LEFT_TURN_LANE_TYPE"] else direction)
        for detector, direction in cross_field("jtll_ddbh", dict).items():
            owners = detector_owners[str(detector)]
            if len(owners) > 1:
                issue(rid, "ambiguous_detector", f"检测器 {detector} 同时分配给 {sorted(owners)}，训练与实时映射需核对")
            try:
                actual = runtime["location_to_intersection_lambda"].get(int(detector))
            except (TypeError, ValueError):
                actual = None
            if actual:
                actual = (runtime["aibi_to_xinkongji"].get(str(actual[0]), actual[0]), actual[1])
            if not actual or tuple(map(str, actual)) != (rid, str(direction)):
                issue(rid, "detector_mapping_mismatch", f"检测器 {detector} 在 cross_info 中为 {rid}/{direction}，实时映射为 {actual}")
        states = road_info.get(rid)
        if not isinstance(states, dict) or not states:
            issue(rid, "missing_road_info", "缺少可用的 road_info 方案", severity="error" if rid in new else "warning")
            continue
        if rid in new and "1" not in states:
            issue(rid, "missing_default_program", "49组的有效默认平台方案1不存在", severity="error")
        if rid in overrides and str(overrides[rid]) not in states:
            issue(rid, "invalid_program_override", f"对外方案号覆盖 {overrides[rid]} 不在已配置方案中", severity="error")
        coverage, patterns = set(), []
        for state, config in states.items():
            if not isinstance(config, dict) or not isinstance(config.get("phase"), list):
                issue(rid, "invalid_program", "方案或 phase 结构无效", severity="error", state=state)
                continue
            phases = config["phase"]
            active = [i for i, name in enumerate(phases) if name]
            if not active or active != list(range(len(active))) or len(active) > 8:
                issue(rid, "phase_slots_invalid", "有效相位须连续位于前8槽；首个零值会结束报文相位列表", severity="error", state=state)
            labels = [name for name in phases if name]
            if all(isinstance(x, str) for x in labels) and len(labels) != len(set(labels)):
                issue(rid, "repeated_phase_label", "存在同名重复相位；保留物理槽位，需要核对是否有意配置", severity="info", state=state)
            pattern, program_coverage = [], set()
            for i in active:
                name = phases[i]
                if not isinstance(name, str) or name not in movements:
                    issue(rid, "unknown_phase", f"相位 {name} 未出现在审计参考的方向映射中；旧策略可能有专用解释", severity="error" if rid in new else "info", state=state)
                else:
                    coverage.update(movements[name])
                    program_coverage.update(movements[name])
                    pattern.append(tuple(sorted(movements[name])))
                    if name not in training:
                        issue(rid, "training_phase_alias", f"相位 {name} 可被新适配器识别，但训练映射未定义该别名；是否用于训练需核对", severity="info", state=state)
                lows, highs = [], []
                for field in ("min_pass_time", "platform_min_pass_time", "max_pass_time", "platform_max_pass_time"):
                    values = config.get(field) or []
                    if not isinstance(values, list) or i >= len(values) or not _number(values[i]):
                        issue(rid, "invalid_phase_bound", f"{field}[{i}] 缺失或不是非负有限数值", severity="error", state=state)
                    elif field in ("min_pass_time", "platform_min_pass_time"):
                        lows.append(values[i])
                    elif values[i] > 0:
                        highs.append(values[i])
                if lows and highs and max(1, math.ceil(max(lows))) > math.floor(min(highs)):
                    issue(rid, "conflicting_phase_bounds", f"相位{i}的有效下限大于上限", severity="error", state=state)
                if not highs:
                    issue(rid, "missing_positive_maximum", f"相位{i}没有正数上限", severity="error", state=state)
            if expected - program_coverage:
                issue(rid, "program_uncovered_controlled_movements", f"本方案未覆盖受控车道方向{sorted(expected - program_coverage)}；需核对是否为分时或专用方案", severity="info", state=state)
            patterns.append(pattern)
        missing = expected - coverage
        if missing:
            issue(rid, "uncovered_controlled_movements", f"受控车道方向 {sorted(missing)} 未被任何已配置方案覆盖；需核实方向与相位含义")
        phase_map = cross_field("phase", dict)
        cycle_key = "zhouqi" if "zhouqi" in cross else "Cycle"
        for cycle in cross_field(cycle_key, list, required=False):
            if not isinstance(cycle, list) or not cycle:
                issue(rid, "invalid_cycle_pattern", "Cycle 应为非空阶段序列的列表", severity="error")
                continue
            labels = [phase_map.get(str(stage)) for stage in cycle]
            if any(label is None for label in labels):
                issue(rid, "cycle_stage_missing", f"周期 {cycle} 包含未定义的阶段编号", severity="error")
            elif all(isinstance(label, str) and label in movements for label in labels):
                pattern = [tuple(sorted(movements[label])) for label in labels]
                if not any(_cycle_equal(pattern, candidate) for candidate in patterns):
                    issue(rid, "cycle_program_order_unmatched", f"周期 {cycle} 的方向序列未与任何方案循环顺序精确匹配；需现场核对", severity="info")
        rules = forced.get(rid, [])
        for rule in rules if isinstance(rules, list) else [rules]:
            if not isinstance(rule, dict):
                continue
            enabled_rule = rule.get("enabled")
            if enabled_rule is not None and (str(enabled_rule).strip().lower() in {"false", "0", "no", "off"} or not enabled_rule):
                continue
            state = next((rule[key] for key in ("zhuangtai", "state", "State") if key in rule), None)
            if _normalized_state(state) not in states:
                issue(rid, "forced_program_missing", f"强制状态 {state} 不在路口方案中，规则可能被忽略")
    return {"schema_version": 1, "scope": "只读静态快照；不证明生产部署配置、实际相位含义或配时效果",
            "pilot_policy": {"mode": mode, "enabled": enabled, "invalid_mode_fell_back_to_legacy": invalid_mode,
                             "mode_source": "显式环境/本地.env" if "AITC_FLOW_ALLOCATOR_PILOT_MODE" in env else "代码默认值",
                             "target_source": "显式环境/本地.env" if selected else "代码默认值",
                             "target_count": len(pilot_roads),
                              "external_data_settings_present": sorted(set(env) & {"AITC_DATA_ROOT", "AITC_FLOW_ALLOCATOR_SHADOW_TABLE", "AITC_FLOW_ALLOCATOR_SHADOW_CROSS_INFO"}),
                              "config_scope": "仅审计指定仓库的lib配置，不读取外部数据路径或经验表",
                             "target_roads_sha256": hashlib.sha256(json.dumps(sorted(pilot_roads)).encode()).hexdigest()},
            "sources": [{"path": path, "sha256": hashlib.sha256(snapshot[path]).hexdigest()} for path in sources],
            "summary": {"roads": len(inventory), "groups": dict(Counter(row["group"] for row in inventory)),
                        "severity": dict(Counter(item["severity"] for item in findings)),
                        "issues": dict(Counter(item["code"] for item in findings))},
            "inventory": inventory, "findings": findings}


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读核对配时调用链与配置一致性，不执行生产算法或修改配置")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--group", choices=("all", "historical", "19", "49"), default="all")
    parser.add_argument("--roads", help="逗号分隔的路口编号")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", type=Path, help="可选：只写一份审计JSON；默认仅输出终端")
    args = parser.parse_args(argv)
    try:
        report = audit(args.root, roads={x.strip() for x in args.roads.split(",") if x.strip()} if args.roads else None, group=args.group)
    except (OSError, ValueError, SyntaxError, KeyError) as error:
        parser.exit(2, f"审计输入不完整：{error}\n")
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        created = False
        try:
            # 仅创建新报告；写入失败或正常中断时清理本次创建的不完整文件。
            with args.output.open("x", encoding="utf-8") as handle:
                created = True
                handle.write(encoded+"\n")
        except BaseException as error:
            if created:
                args.output.unlink(missing_ok=True)
            if isinstance(error, OSError):
                parser.exit(2, f"报告未写入：{error}\n")
            raise
    if args.format == "json":
        print(encoded)
    else:
        print("只读配置审计（配置疑点不等同于现场故障）")
        print(json.dumps(report["summary"], ensure_ascii=False))
        for issue in report["findings"]:
            print(f"[{issue['severity']}] [{issue['group']}] {issue['road_id']} {issue['code']}: {issue['message']}")
    return 1 if report["summary"]["severity"].get("error", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
