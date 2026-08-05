# import ast
# import copy
# import json
# import os
# import re
# import threading
# import pprint
# from datetime import date, datetime
#
# try:
#     from chinese_calendar import is_workday as _is_workday
# except Exception:
#     _is_workday = None
#
#
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# PROJECT_DIR = os.path.dirname(BASE_DIR)
#
#
# def _project_path(*parts):
#     return os.path.join(PROJECT_DIR, *parts)
#
#
# def _rel_path(path):
#     return os.path.relpath(path, PROJECT_DIR).replace(os.sep, "/")
#
#
# ROAD_INFO_PATH = _project_path("lib", "road_info.json")
# CROSS_INFO_PATH = _project_path("lib", "cross_info.json")
# LAMBDAS_PATH = _project_path("Lambdas.py")
# DQN_SELECT_PATH = _project_path("lib", "DQN_Select.py")
# GLOBAL_COORDINATE_PATH = _project_path("lib", "Global_intersection_coordinate.py")
# SCHEDULE_JSON_DIR = _project_path("time_schedule", "schedule_json")
#
# _write_lock = threading.Lock()
# _DIRECTIONS = ("U", "D", "L", "R")
# _ROAD_STATE_FIELDS = (
#     "phase",
#     "max_pass_time",
#     "min_pass_time",
#     "platform_max_pass_time",
#     "platform_min_pass_time",
#     "phase_weight",
# )
# _GLOBAL_GROUP_ALIASES = {
#     "aibi_road": ("aibi_road", "shipin1_road"),
#     "online": ("online", "intern_road_id"),
#     "onlin": ("online", "intern_road_id"),
#     "shipin1_road": ("aibi_road", "shipin1_road"),
#     "intern_road_id": ("online", "intern_road_id"),
# }
# _CROSS_TYPE_OPTIONS = ("Radar", "Video")
#
#
# def _read_json(path):
#     if not os.path.exists(path):
#         return {}
#     with open(path, "r", encoding="utf-8") as f:
#         return json.load(f)
#
#
# def _write_json(path, data):
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=4)
#
#
# def _normalize_key(value):
#     if value is None:
#         raise ValueError("missing required field: Cross_id")
#     return str(value).strip()
#
#
# def _get_any(mapping, *keys, default=None):
#     for key in keys:
#         if isinstance(mapping, dict) and key in mapping:
#             return mapping[key]
#     return default
#
#
# def _normalize_len10(values, field_name):
#     if not isinstance(values, list):
#         raise ValueError(f"{field_name} must be a list")
#     if len(values) > 10:
#         raise ValueError(f"{field_name} length must be <= 10")
#     return list(values) + [0] * (10 - len(values))
#
#
# def _normalize_road_info(road_info):
#     if road_info is None:
#         return None
#     if not isinstance(road_info, dict) or not road_info:
#         raise ValueError("road_info must be a non-empty JSON object")
#
#     normalized = {}
#     for state, state_config in road_info.items():
#         state_key = _normalize_key(state)
#         if not isinstance(state_config, dict):
#             raise ValueError(f"road_info[{state_key}] must be a JSON object")
#
#         normalized_state = {}
#         for field in _ROAD_STATE_FIELDS:
#             if field not in state_config:
#                 raise ValueError(f"road_info[{state_key}] missing field: {field}")
#             normalized_state[field] = _normalize_len10(
#                 state_config[field],
#                 f"road_info[{state_key}].{field}",
#             )
#         normalized[state_key] = normalized_state
#     return normalized
#
#
# def _normalize_phase_map(value):
#     if not isinstance(value, dict) or not value:
#         raise ValueError("phase must be a non-empty JSON object")
#     return {_normalize_key(k): v for k, v in value.items()}
#
#
# def _normalize_lane_no(value):
#     if not isinstance(value, dict):
#         raise ValueError("LaneNo/laneno must be a JSON object")
#
#     normalized = {direction: {} for direction in _DIRECTIONS}
#     for direction, lanes in value.items():
#         direction_key = str(direction).upper()
#         if direction_key not in _DIRECTIONS:
#             raise ValueError(f"invalid LaneNo direction: {direction}")
#         if lanes in (None, ""):
#             lanes = {}
#         if not isinstance(lanes, dict):
#             raise ValueError(f"LaneNo[{direction_key}] must be a JSON object")
#         normalized[direction_key] = {_normalize_key(k): v for k, v in lanes.items()}
#     return normalized
#
#
# def _normalize_jtll(value):
#     if not isinstance(value, dict) or not value:
#         raise ValueError("jtll_ddbh must be a non-empty JSON object")
#
#     normalized = {}
#     for detector_id, direction in value.items():
#         detector_key = _normalize_key(detector_id)
#         if not detector_key.isdigit():
#             raise ValueError(f"jtll_ddbh detector id must be numeric: {detector_key}")
#         direction_key = str(direction).upper()
#         if direction_key not in _DIRECTIONS:
#             raise ValueError(f"jtll_ddbh[{detector_key}] direction must be one of U/D/L/R")
#         normalized[detector_key] = direction_key
#     return normalized
#
#
# def _normalize_global_group(value):
#     if value in (None, ""):
#         value = "aibi_road"
#     key = str(value).strip().lower()
#     if key not in _GLOBAL_GROUP_ALIASES:
#         raise ValueError("code_config.global_group must be one of: aibi_road, online")
#     return _GLOBAL_GROUP_ALIASES[key]
#
#
# def _normalize_cross_type(value):
#     if value in (None, ""):
#         return "Radar"
#     key = str(value).strip().lower()
#     for option in _CROSS_TYPE_OPTIONS:
#         if key == option.lower():
#             return option
#     raise ValueError("code_config.cross_type must be one of: Radar, Video")
#
#
# def _normalize_zhouqi(value):
#     if not isinstance(value, list) or not value:
#         raise ValueError("zhouqi must be a non-empty list")
#
#     normalized = []
#     for index, cycle in enumerate(value):
#         if not isinstance(cycle, list) or not cycle:
#             raise ValueError(f"zhouqi[{index}] must be a non-empty list")
#         normalized.append([int(item) for item in cycle])
#     return normalized
#
#
# def _normalize_cross_info(payload):
#     nested = payload.get("cross_info") if isinstance(payload.get("cross_info"), dict) else {}
#     phase = _get_any(nested, "phase", default=_get_any(payload, "phase"))
#     lane_no = _get_any(
#         nested,
#         "LaneNo",
#         "laneno",
#         "laneNo",
#         default=_get_any(payload, "LaneNo", "laneno", "laneNo"),
#     )
#     jtll = _get_any(nested, "jtll_ddbh", default=_get_any(payload, "jtll_ddbh"))
#     zhouqi = _get_any(nested, "zhouqi", default=_get_any(payload, "zhouqi"))
#
#     if all(item is None for item in (phase, lane_no, jtll, zhouqi)):
#         return None
#     if any(item is None for item in (phase, lane_no, jtll, zhouqi)):
#         raise ValueError("cross_info requires phase, LaneNo/laneno, jtll_ddbh, and zhouqi")
#
#     return {
#         "phase": _normalize_phase_map(phase),
#         "LaneNo": _normalize_lane_no(lane_no),
#         "jtll_ddbh": _normalize_jtll(jtll),
#         "zhouqi": _normalize_zhouqi(zhouqi),
#     }
#
#
# def _normalize_code_config(payload):
#     raw = payload.get("code_config") if isinstance(payload.get("code_config"), dict) else {}
#     enabled = bool(raw.get("enabled", payload.get("update_code", True)))
#     global_group_alias, global_group_internal = _normalize_global_group(
#         raw.get("global_group", _get_any(payload, "global_group", default="aibi_road"))
#     )
#     return {
#         "enabled": enabled,
#         "update_lambdas": bool(raw.get("update_lambdas", True)),
#         "lambda_config_keys": raw.get(
#             "lambda_config_keys",
#             ["flow", "queue", "stage", "extend"],
#         ),
#         "update_global": bool(raw.get("update_global", True)),
#         "global_group": global_group_internal,
#         "global_group_alias": global_group_alias,
#         "update_dqn": bool(raw.get("update_dqn", True)),
#         "cross_type": _normalize_cross_type(raw.get("cross_type", _get_any(payload, "cross_type"))),
#     }
#
#
# def _normalize_intersection_payload(payload):
#     if not isinstance(payload, dict):
#         raise ValueError("payload must be a JSON object")
#
#     cross_id = _normalize_key(_get_any(payload, "Cross_id", "cross_id", "CrossID"))
#     if not cross_id.isdigit():
#         raise ValueError("Cross_id must be numeric")
#
#     road_info = _normalize_road_info(payload.get("road_info"))
#     cross_info = _normalize_cross_info(payload)
#     code_config = _normalize_code_config(payload)
#
#     if road_info is None and cross_info is None and not code_config["enabled"]:
#         raise ValueError("nothing to update: provide road_info, cross_info, or enable code_config")
#
#     return {
#         "cross_id": cross_id,
#         "road_info": road_info,
#         "cross_info": cross_info,
#         "code_config": code_config,
#     }
#
#
# def _normalize_batch_payload(payload):
#     if isinstance(payload, dict) and isinstance(payload.get("items"), list):
#         items = payload["items"]
#     else:
#         items = [payload]
#     if not items:
#         raise ValueError("items must not be empty")
#     return [_normalize_intersection_payload(item) for item in items]
#
#
# def _contains_cross_id(block, cross_id):
#     return (
#         f"'{cross_id}'" in block
#         or f'"{cross_id}"' in block
#         or re.search(rf"(?<!\d){re.escape(cross_id)}(?!\d)", block) is not None
#     )
#
#
# def _find_brace_block(text, marker):
#     start = text.find(marker)
#     if start < 0:
#         raise ValueError(f"cannot find marker: {marker}")
#     open_index = text.find("{", start)
#     if open_index < 0:
#         raise ValueError(f"cannot find opening brace after marker: {marker}")
#
#     depth = 0
#     quote = None
#     escape = False
#     for index in range(open_index, len(text)):
#         char = text[index]
#         if quote:
#             if escape:
#                 escape = False
#             elif char == "\\":
#                 escape = True
#             elif char == quote:
#                 quote = None
#             continue
#         if char in ("'", '"'):
#             quote = char
#         elif char == "{":
#             depth += 1
#         elif char == "}":
#             depth -= 1
#             if depth == 0:
#                 return open_index, index
#     raise ValueError(f"cannot find closing brace after marker: {marker}")
#
#
# def _ensure_dict_entry(text, marker, cross_id, cross_type):
#     start, end = _find_brace_block(text, marker)
#     block = text[start:end + 1]
#     if _contains_cross_id(block, cross_id):
#         return text, False
#
#     entry = (
#         f"\n'{cross_id}': {{\n"
#         f"        \"Cross_type\": \"{cross_type}\"\n"
#         f"    }},\n"
#     )
#     return text[:end] + entry + text[end:], True
#
#
# def _ensure_set_entry(text, marker, cross_id):
#     start, end = _find_brace_block(text, marker)
#     block = text[start:end + 1]
#     if _contains_cross_id(block, cross_id):
#         return text, False
#     return text[:end] + f"\n    {cross_id},\n" + text[end:], True
#
#
# def _ensure_config_lambda_entry(text, key, cross_id):
#     pattern = re.compile(
#         rf"(?P<prefix>['\"]{re.escape(key)}['\"]\s*:\s*\[)(?P<body>.*?)(?P<suffix>\n\s*\],?)",
#         re.S,
#     )
#     match = pattern.search(text)
#     if not match:
#         raise ValueError(f"cannot find config_lambda list: {key}")
#     if _contains_cross_id(match.group("body"), cross_id):
#         return text, False
#     replacement = (
#         match.group("prefix")
#         + match.group("body")
#         + f'\n"{cross_id}",'
#         + match.group("suffix")
#     )
#     return text[:match.start()] + replacement + text[match.end():], True
#
#
# def _ensure_intersection_list_entry(text, cross_id):
#     pattern = re.compile(
#         r"(?P<prefix>intersection_list\s*=\s*\[)(?P<body>.*?)(?P<suffix>\n\])",
#         re.S,
#     )
#     match = pattern.search(text)
#     if not match:
#         raise ValueError("cannot find intersection_list")
#     if _contains_cross_id(match.group("body"), cross_id):
#         return text, False
#     replacement = (
#         match.group("prefix")
#         + match.group("body")
#         + f'\n"{cross_id}",'
#         + match.group("suffix")
#     )
#     return text[:match.start()] + replacement + text[match.end():], True
#
#
# def _ensure_location_mappings(text, cross_id, jtll_ddbh):
#     start, end = _find_brace_block(text, "location_to_intersection_lambda")
#     block = text[start:end + 1]
#     additions = []
#     for detector_id, direction in jtll_ddbh.items():
#         if re.search(rf"(?m)^\s*{re.escape(detector_id)}\s*:", block):
#             continue
#         additions.append(f"{detector_id}:('{cross_id}','{direction}'),")
#     if not additions:
#         return text, False
#     return text[:end] + "\n" + "\n".join(additions) + "\n" + text[end:], True
#
#
# def _update_lambdas_file(cross_id, cross_info, code_config, dry_run):
#     if cross_info is None:
#         raise ValueError("cross_info is required when update_lambdas is true")
#     text = _read_text(LAMBDAS_PATH)
#     changed = []
#
#     for key in code_config["lambda_config_keys"]:
#         text, did_change = _ensure_config_lambda_entry(text, str(key), cross_id)
#         if did_change:
#             changed.append(f"config_lambda.{key}")
#
#     text, did_change = _ensure_intersection_list_entry(text, cross_id)
#     if did_change:
#         changed.append("intersection_list")
#
#     text, did_change = _ensure_location_mappings(text, cross_id, cross_info["jtll_ddbh"])
#     if did_change:
#         changed.append("location_to_intersection_lambda")
#
#     if changed and not dry_run:
#         _write_text(LAMBDAS_PATH, text)
#     return changed
#
#
# def _update_global_coordinate_file(cross_id, code_config, dry_run):
#     text = _read_text(GLOBAL_COORDINATE_PATH)
#     text, did_change = _ensure_set_entry(text, code_config["global_group"], cross_id)
#     if did_change and not dry_run:
#         _write_text(GLOBAL_COORDINATE_PATH, text)
#     return [code_config.get("global_group_alias", code_config["global_group"])] if did_change else []
#
#
# def _dqn_route_snippet(cross_id):
#     return (
#         f"        elif cross_id == '{cross_id}':\n"
#         f"            return DQN_select_{cross_id}(traffic_vector, queue_vector, traffic_vector_duration2, current_time,\n"
#         f"                                  flow_map_single_intersection, queue_map_single_intersection,\n"
#         f"                                  stage_map_single_intersection, extend_map_single_intersection, 0, cur_flow_pre_map, cur_queue_pre_map)\n"
#     )
#
#
# def _dqn_function_snippet(cross_id):
#     return (
#         f"\n\ndef DQN_select_{cross_id}(traffic_vector, queue_vector, traffic_vector_duration2,current_time,"
#         f"flow_map_single_intersection,queue_map_single_intersection,stage_map_single_intersection,"
#         f"extend_map_single_intersection,coordinate_map_set,cur_flow_pre_map,cur_queue_pre_map):\n"
#         f"    model_map = get_model_map(traffic_vector, queue_map_single_intersection, stage_map_single_intersection)\n"
#         f"    EXP_map = get_exp(traffic_vector, traffic_vector_duration2)\n\n"
#         f"    coordinate_set = {{\"Start1\":1,\"start2\":0}}\n"
#         f"    print(\"{cross_id}-----------------------------------------------\")\n\n"
#         f"    print(flow_map_single_intersection)\n\n"
#         f"    print(\"{cross_id}-----------------------------------------------\")\n\n"
#         f"    sch=chuli_shuju(\"{cross_id}\", flow_map_single_intersection,extend_map_single_intersection)\n"
#         f"    return sch,coordinate_set,model_map,EXP_map\n"
#     )
#
#
# def _update_dqn_select_file(cross_id, code_config, dry_run):
#     text = _read_text(DQN_SELECT_PATH)
#     changed = []
#
#     text, did_change = _ensure_dict_entry(
#         text,
#         "Cross_Video",
#         cross_id,
#         code_config["cross_type"],
#     )
#     if did_change:
#         changed.append("Cross_Video")
#
#     if f"elif cross_id == '{cross_id}'" not in text:
#         marker = "    else:\n        sch = [0] * 10"
#         index = text.find(marker)
#         if index < 0:
#             raise ValueError("cannot find DQN_select route insertion point")
#         text = text[:index] + _dqn_route_snippet(cross_id) + text[index:]
#         changed.append("DQN_select route")
#
#     if f"def DQN_select_{cross_id}(" not in text:
#         marker = "\ndef DQN_select_1300271("
#         index = text.find(marker)
#         if index < 0:
#             raise ValueError("cannot find DQN_select function insertion point")
#         text = text[:index] + _dqn_function_snippet(cross_id) + text[index:]
#         changed.append(f"DQN_select_{cross_id}")
#
#     if changed and not dry_run:
#         _write_text(DQN_SELECT_PATH, text)
#     return changed
#
#
# def _remove_literal_entry(body, cross_id):
#     updated = re.sub(rf"\s*['\"]{re.escape(cross_id)}['\"]\s*,?", "", body)
#     updated = re.sub(rf"\s*(?<!\d){re.escape(cross_id)}(?!\d)\s*,?", "", updated)
#     return updated
#
#
# def _remove_config_lambda_entry(text, key, cross_id):
#     pattern = re.compile(
#         rf"(?P<prefix>['\"]{re.escape(key)}['\"]\s*:\s*\[)(?P<body>.*?)(?P<suffix>\n\s*\],?)",
#         re.S,
#     )
#     match = pattern.search(text)
#     if not match:
#         return text, False
#     body = match.group("body")
#     updated_body = _remove_literal_entry(body, cross_id)
#     if updated_body == body:
#         return text, False
#     replacement = match.group("prefix") + updated_body + match.group("suffix")
#     return text[:match.start()] + replacement + text[match.end():], True
#
#
# def _remove_intersection_list_entry(text, cross_id):
#     pattern = re.compile(
#         r"(?P<prefix>intersection_list\s*=\s*\[)(?P<body>.*?)(?P<suffix>\n\])",
#         re.S,
#     )
#     match = pattern.search(text)
#     if not match:
#         return text, False
#     body = match.group("body")
#     updated_body = _remove_literal_entry(body, cross_id)
#     if updated_body == body:
#         return text, False
#     replacement = match.group("prefix") + updated_body + match.group("suffix")
#     return text[:match.start()] + replacement + text[match.end():], True
#
#
# def _remove_location_mappings(text, cross_id, cross_info):
#     start, end = _find_brace_block(text, "location_to_intersection_lambda")
#     block = text[start:end + 1]
#     updated_block = block
#
#     detector_ids = []
#     if isinstance(cross_info, dict):
#         detector_ids = list((cross_info.get("jtll_ddbh") or {}).keys())
#
#     for detector_id in detector_ids:
#         updated_block = re.sub(
#             rf"(?m)^\s*{re.escape(str(detector_id))}\s*:\s*\([^)]*\),\s*\n?",
#             "",
#             updated_block,
#         )
#
#     updated_block = re.sub(
#         rf"(?m)^\s*[^:\n]+:\s*\(['\"]{re.escape(cross_id)}['\"],\s*['\"][UDLR]['\"]\),\s*\n?",
#         "",
#         updated_block,
#     )
#
#     if updated_block == block:
#         return text, False
#     return text[:start] + updated_block + text[end + 1:], True
#
#
# def _remove_lambdas_file(cross_id, cross_info, code_config, dry_run):
#     text = _read_text(LAMBDAS_PATH)
#     changed = []
#
#     for key in code_config["lambda_config_keys"]:
#         text, did_change = _remove_config_lambda_entry(text, str(key), cross_id)
#         if did_change:
#             changed.append(f"config_lambda.{key}")
#
#     text, did_change = _remove_intersection_list_entry(text, cross_id)
#     if did_change:
#         changed.append("intersection_list")
#
#     text, did_change = _remove_location_mappings(text, cross_id, cross_info)
#     if did_change:
#         changed.append("location_to_intersection_lambda")
#
#     if changed and not dry_run:
#         _write_text(LAMBDAS_PATH, text)
#     return changed
#
#
# def _remove_set_entry(text, marker, cross_id):
#     start, end = _find_brace_block(text, marker)
#     block = text[start:end + 1]
#     updated_block = _remove_literal_entry(block, cross_id)
#     if updated_block == block:
#         return text, False
#     return text[:start] + updated_block + text[end + 1:], True
#
#
# def _remove_global_coordinate_file(cross_id, code_config, dry_run):
#     text = _read_text(GLOBAL_COORDINATE_PATH)
#     text, did_change = _remove_set_entry(text, code_config["global_group"], cross_id)
#     if did_change and not dry_run:
#         _write_text(GLOBAL_COORDINATE_PATH, text)
#     return [code_config.get("global_group_alias", code_config["global_group"])] if did_change else []
#
#
# def _remove_dqn_select_file(cross_id, dry_run):
#     text = _read_text(DQN_SELECT_PATH)
#     changed = []
#
#     updated = re.sub(
#         rf"\n'{re.escape(cross_id)}':\s*\{{\s*\"Cross_type\"\s*:\s*\"[^\"]+\"\s*\}},\s*\n",
#         "\n",
#         text,
#         flags=re.S,
#     )
#     if updated != text:
#         text = updated
#         changed.append("Cross_Video")
#
#     updated = re.sub(
#         rf"\n\s*elif cross_id == '{re.escape(cross_id)}':\n\s*return DQN_select_{re.escape(cross_id)}\(.*?cur_queue_pre_map\)\n",
#         "\n",
#         text,
#         flags=re.S,
#     )
#     if updated != text:
#         text = updated
#         changed.append("DQN_select route")
#
#     updated = re.sub(
#         rf"\n\ndef DQN_select_{re.escape(cross_id)}\(.*?return sch,coordinate_set,model_map,EXP_map\n",
#         "\n",
#         text,
#         flags=re.S,
#     )
#     if updated != text:
#         text = updated
#         changed.append(f"DQN_select_{cross_id}")
#
#     if changed and not dry_run:
#         _write_text(DQN_SELECT_PATH, text)
#     return changed
#
#
# def _read_text(path):
#     with open(path, "r", encoding="utf-8") as f:
#         return f.read()
#
#
# def _write_text(path, text):
#     with open(path, "w", encoding="utf-8") as f:
#         f.write(text)
#
#
# def _apply_single_intersection_config(item, dry_run):
#     cross_id = item["cross_id"]
#     result = {
#         "cross_id": cross_id,
#         "saved": not dry_run,
#         "files": {},
#         "code_changes": {},
#     }
#
#     if item["road_info"] is not None:
#         road_data = _read_json(ROAD_INFO_PATH)
#         result["files"]["road_info.json"] = {
#             "path": _rel_path(ROAD_INFO_PATH),
#             "operation": "updated" if cross_id in road_data else "created",
#         }
#         if not dry_run:
#             road_data[cross_id] = item["road_info"]
#             _write_json(ROAD_INFO_PATH, road_data)
#
#     if item["cross_info"] is not None:
#         cross_data = _read_json(CROSS_INFO_PATH)
#         result["files"]["cross_info.json"] = {
#             "path": _rel_path(CROSS_INFO_PATH),
#             "operation": "updated" if cross_id in cross_data else "created",
#         }
#         if not dry_run:
#             cross_data[cross_id] = item["cross_info"]
#             _write_json(CROSS_INFO_PATH, cross_data)
#
#     code_config = item["code_config"]
#     if code_config["enabled"]:
#         if code_config["update_lambdas"]:
#             result["code_changes"]["Lambdas.py"] = _update_lambdas_file(
#                 cross_id,
#                 item["cross_info"],
#                 code_config,
#                 dry_run,
#             )
#         if code_config["update_global"]:
#             result["code_changes"]["Global_intersection_coordinate.py"] = (
#                 _update_global_coordinate_file(cross_id, code_config, dry_run)
#             )
#         if code_config["update_dqn"]:
#             result["code_changes"]["DQN_Select.py"] = _update_dqn_select_file(
#                 cross_id,
#                 code_config,
#                 dry_run,
#             )
#
#     return result
#
#
# def validate_and_save_intersection_config(payload, dry_run=False):
#     try:
#         items = _normalize_batch_payload(payload)
#         if dry_run:
#             results = [_apply_single_intersection_config(item, True) for item in items]
#         else:
#             with _write_lock:
#                 results = [_apply_single_intersection_config(item, False) for item in items]
#         return {
#             "status": "validated" if dry_run else "success",
#             "saved": not dry_run,
#             "message": "validation success" if dry_run else "save success",
#             "items": results,
#         }
#     except Exception as error:
#         return {
#             "status": "error",
#             "saved": False,
#             "reason": str(error),
#         }
#
#
# def _normalize_road_info_payload(payload):
#     if not isinstance(payload, dict):
#         raise ValueError("payload must be a JSON object")
#     cross_id = _normalize_key(_get_any(payload, "Cross_id", "cross_id", "CrossID"))
#     if not cross_id.isdigit():
#         raise ValueError("Cross_id must be numeric")
#     road_info = _normalize_road_info(payload.get("road_info"))
#     if road_info is None:
#         raise ValueError("road_info is required")
#     return {
#         "cross_id": cross_id,
#         "road_info": road_info,
#     }
#
#
# def _normalize_road_info_batch_payload(payload):
#     if isinstance(payload, dict) and isinstance(payload.get("items"), list):
#         items = payload["items"]
#     else:
#         items = [payload]
#     if not items:
#         raise ValueError("items must not be empty")
#     return [_normalize_road_info_payload(item) for item in items]
#
#
# def _apply_single_road_info_config(item, dry_run):
#     cross_id = item["cross_id"]
#     road_data = _read_json(ROAD_INFO_PATH)
#     result = {
#         "Cross_id": cross_id,
#         "saved": not dry_run,
#         "file": {
#             "path": _rel_path(ROAD_INFO_PATH),
#             "operation": "updated" if cross_id in road_data else "created",
#         },
#     }
#     if not dry_run:
#         road_data[cross_id] = item["road_info"]
#         _write_json(ROAD_INFO_PATH, road_data)
#     return result
#
#
# def validate_and_save_road_info_config(payload, dry_run=False):
#     try:
#         items = _normalize_road_info_batch_payload(payload)
#         if dry_run:
#             results = [_apply_single_road_info_config(item, True) for item in items]
#         else:
#             with _write_lock:
#                 results = [_apply_single_road_info_config(item, False) for item in items]
#         return {
#             "status": "validated" if dry_run else "success",
#             "saved": not dry_run,
#             "message": "validation success" if dry_run else "save success",
#             "items": results,
#         }
#     except Exception as error:
#         return {
#             "status": "error",
#             "saved": False,
#             "reason": str(error),
#         }
#
#
# def get_road_info_config(cross_id):
#     cross_key = _normalize_key(cross_id)
#     road_data = _read_json(ROAD_INFO_PATH)
#     return {
#         "Cross_id": cross_key,
#         "file": _rel_path(ROAD_INFO_PATH),
#         "road_info": copy.deepcopy(road_data.get(cross_key)),
#     }
#
#
# def list_road_info_configs(full=False):
#     road_data = _read_json(ROAD_INFO_PATH)
#     result = {
#         "status": "success",
#         "file": _rel_path(ROAD_INFO_PATH),
#         "count": len(road_data),
#         "cross_ids": sorted(road_data.keys(), key=str),
#     }
#     if full:
#         result["road_info"] = road_data
#     return result
#
#
# def delete_road_info_config(payload, dry_run=False):
#     try:
#         if not isinstance(payload, dict):
#             raise ValueError("payload must be a JSON object")
#         if isinstance(payload.get("items"), list):
#             cross_ids = [
#                 _normalize_key(_get_any(item, "Cross_id", "cross_id", "CrossID"))
#                 for item in payload["items"]
#             ]
#         else:
#             cross_ids = [_normalize_key(_get_any(payload, "Cross_id", "cross_id", "CrossID"))]
#         if not cross_ids:
#             raise ValueError("items must not be empty")
#         for cross_id in cross_ids:
#             if not cross_id.isdigit():
#                 raise ValueError("Cross_id must be numeric")
#
#         files = []
#         with _write_lock:
#             road_data = _read_json(ROAD_INFO_PATH)
#             changed = False
#             for cross_id in cross_ids:
#                 existed = cross_id in road_data
#                 files.append({
#                     "Cross_id": cross_id,
#                     "path": _rel_path(ROAD_INFO_PATH),
#                     "operation": "deleted" if existed else "not_found",
#                 })
#                 if existed and not dry_run:
#                     del road_data[cross_id]
#                     changed = True
#             if changed:
#                 _write_json(ROAD_INFO_PATH, road_data)
#
#         return {
#             "status": "validated" if dry_run else "success",
#             "saved": not dry_run,
#             "message": "validation success" if dry_run else "delete success",
#             "files": files,
#         }
#     except Exception as error:
#         return {
#             "status": "error",
#             "saved": False,
#             "reason": str(error),
#         }
#
#
# def get_intersection_config(cross_id):
#     cross_key = _normalize_key(cross_id)
#     road_data = _read_json(ROAD_INFO_PATH)
#     cross_data = _read_json(CROSS_INFO_PATH)
#     return {
#         "Cross_id": cross_key,
#         "files": {
#             "road_info": _rel_path(ROAD_INFO_PATH),
#             "cross_info": _rel_path(CROSS_INFO_PATH),
#         },
#         "road_info": copy.deepcopy(road_data.get(cross_key)),
#         "cross_info": copy.deepcopy(cross_data.get(cross_key)),
#     }
#
#
# def list_intersection_configs(full=False):
#     road_data = _read_json(ROAD_INFO_PATH)
#     cross_data = _read_json(CROSS_INFO_PATH)
#     cross_ids = sorted(set(road_data.keys()) | set(cross_data.keys()), key=str)
#     result = {
#         "status": "success",
#         "files": {
#             "road_info": _rel_path(ROAD_INFO_PATH),
#             "cross_info": _rel_path(CROSS_INFO_PATH),
#         },
#         "count": len(cross_ids),
#         "cross_ids": cross_ids,
#     }
#     if full:
#         result["road_info"] = road_data
#         result["cross_info"] = cross_data
#     return result
#
#
# def _frontend_code_config_options():
#     return {
#         "global_group": ["aibi_road", "online"],
#         "cross_type": list(_CROSS_TYPE_OPTIONS),
#     }
#
#
# def _normalize_online_direction(value):
#     if value is None:
#         return None
#     direction = str(value).strip().upper()
#     if not direction:
#         raise ValueError("rid_list.direction must not be empty")
#     if re.search(r"[^A-Z0-9]", direction):
#         raise ValueError("rid_list.direction must contain only letters and numbers")
#     return direction
#
#
# def _normalize_online_rid_list(value):
#     if not isinstance(value, list):
#         raise ValueError("rid_list must be a list")
#
#     normalized = []
#     seen = set()
#     for index, row in enumerate(value):
#         if isinstance(row, dict):
#             rid = _normalize_key(_get_any(row, "rid", "RID", "road_id"))
#             direction = _normalize_online_direction(_get_any(row, "direction", "Direction"))
#         elif isinstance(row, (list, tuple)) and len(row) >= 2:
#             rid = _normalize_key(row[0])
#             direction = _normalize_online_direction(row[1])
#         else:
#             raise ValueError(f"rid_list[{index}] must be an object with rid and direction")
#
#         if not rid:
#             raise ValueError(f"rid_list[{index}].rid must not be empty")
#         if rid in seen:
#             raise ValueError(f"duplicate rid in rid_list: {rid}")
#         seen.add(rid)
#         normalized.append({"rid": rid, "direction": direction})
#
#     return normalized
#
#
# def _normalize_online_intersection_payload(payload):
#     if not isinstance(payload, dict):
#         raise ValueError("payload must be a JSON object")
#
#     cross_id = _normalize_key(_get_any(payload, "Cross_id", "cross_id", "CrossID"))
#     if not cross_id.isdigit():
#         raise ValueError("Cross_id must be numeric")
#
#     rid_list = _normalize_online_rid_list(_get_any(payload, "rid_list", "rids"))
#     return {
#         "cross_id": cross_id,
#         "cross_id_int": int(cross_id),
#         "rid_list": rid_list,
#     }
#
#
# def _find_assignment_node(path, assignment_name):
#     text = _read_text(path)
#     tree = ast.parse(text)
#     for node in tree.body:
#         if isinstance(node, ast.Assign):
#             for target in node.targets:
#                 if isinstance(target, ast.Name) and target.id == assignment_name:
#                     return text, node
#     raise ValueError(f"cannot find assignment: {assignment_name}")
#
#
# def _load_python_assignment(path, assignment_name):
#     text, node = _find_assignment_node(path, assignment_name)
#     value = node.value
#     if (
#         isinstance(value, ast.Call)
#         and isinstance(value.func, ast.Attribute)
#         and value.func.attr == "copy"
#         and not value.args
#         and not value.keywords
#     ):
#         value = value.func.value
#     return ast.literal_eval(value)
#
#
# def _replace_python_assignment(path, assignment_name, new_rhs_text, dry_run):
#     text, node = _find_assignment_node(path, assignment_name)
#     lines = text.splitlines(keepends=True)
#     start_line = node.lineno - 1
#     end_line = node.end_lineno - 1
#     prefix = "".join(lines[:start_line])
#     suffix = "".join(lines[end_line + 1:])
#     indent = " " * node.col_offset
#     replacement = f"{indent}{assignment_name} = {new_rhs_text}\n"
#     new_text = prefix + replacement + suffix
#     if not dry_run:
#         _write_text(path, new_text)
#     return _rel_path(path)
#
#
# def _format_python_literal(value):
#     return pprint.pformat(value, width=96, sort_dicts=True)
#
#
# def _load_lambdas_online_config(cross_id):
#     cross_id = str(cross_id)
#     online_data_map = _load_python_assignment(LAMBDAS_PATH, "online_data_map_lambda")
#     intersection_to_rid = _load_python_assignment(LAMBDAS_PATH, "intersection_to_rid_lambda")
#     rid_rows = []
#     missing_from_cache = []
#
#     for rid, direction in intersection_to_rid.get(cross_id, []):
#         rid = str(rid)
#         in_cache = rid in online_data_map
#         rid_rows.append({
#             "rid": rid,
#             "direction": direction,
#             "in_online_data_map_lambda": in_cache,
#         })
#         if not in_cache:
#             missing_from_cache.append(rid)
#
#     return rid_rows, missing_from_cache
#
#
# def _load_global_online_config(cross_id, rid_rows):
#     cross_id_int = int(cross_id) if str(cross_id).isdigit() else cross_id
#     intern_road_id = _load_python_assignment(GLOBAL_COORDINATE_PATH, "intern_road_id")
#     online_map_info = _load_python_assignment(GLOBAL_COORDINATE_PATH, "online_map_info")
#
#     global_rows = []
#     missing_from_global_map = []
#     for row in rid_rows:
#         rid = row["rid"]
#         mapping = online_map_info.get(rid)
#         direction = None
#         in_global_map = False
#         if isinstance(mapping, dict):
#             if cross_id_int in mapping:
#                 direction = mapping[cross_id_int]
#                 in_global_map = True
#             elif str(cross_id) in mapping:
#                 direction = mapping[str(cross_id)]
#                 in_global_map = True
#         elif isinstance(mapping, list) and len(mapping) >= 2:
#             if str(mapping[0]) == str(cross_id):
#                 direction = mapping[1]
#                 in_global_map = True
#
#         global_row = dict(row)
#         global_row["online_map_info_direction"] = direction
#         global_row["in_online_map_info"] = in_global_map
#         global_rows.append(global_row)
#         if not in_global_map:
#             missing_from_global_map.append(rid)
#
#     return {
#         "in_intern_road_id": cross_id_int in intern_road_id,
#         "global_online_map_info": global_rows,
#         "missing_from_online_map_info": missing_from_global_map,
#     }
#
#
# def get_online_intersection_config(cross_id):
#     cross_key = _normalize_key(cross_id)
#     if not cross_key.isdigit():
#         raise ValueError("Cross_id must be numeric")
#
#     rid_rows, missing_from_cache = _load_lambdas_online_config(cross_key)
#     global_config = _load_global_online_config(cross_key, rid_rows)
#     rid_list = [
#         {"rid": row["rid"], "direction": row["direction"]}
#         for row in rid_rows
#     ]
#     return {
#         "code": 0,
#         "status": "success",
#         "Cross_id": cross_key,
#         "cross_id": cross_key,
#         "rid_list": rid_list,
#         "display_target": "after save, refresh this endpoint and render rid_list in the detail table",
#         "in_intersection_list": _contains_cross_id(
#             _read_text(LAMBDAS_PATH), cross_key
#         ),
#         "intersection_to_rid_lambda": rid_rows,
#         "online_data_map_lambda_rids": [
#             row["rid"] for row in rid_rows if row["in_online_data_map_lambda"]
#         ],
#         "missing_from_online_data_map_lambda": missing_from_cache,
#         **global_config,
#     }
#
#
# def list_online_intersection_configs(full=False):
#     intersection_to_rid = _parse_literal_from_source(LAMBDAS_PATH, "intersection_to_rid_lambda")
#     cross_ids = sorted(intersection_to_rid.keys(), key=str)
#     result = {
#         "code": 0,
#         "status": "success",
#         "count": len(cross_ids),
#         "cross_ids": cross_ids,
#         "display_target": "use cross_ids for the online intersection list; query detail by Cross_id",
#     }
#     if full:
#         result["items"] = [
#             get_online_intersection_config(cross_id)
#             for cross_id in cross_ids
#         ]
#     return result
#
#
# def _replace_mapping_entry(text, marker, key, value_text):
#     start, end = _find_brace_block(text, marker)
#     block = text[start:end + 1]
#     key_pattern = rf"(?m)^(?P<indent>\s*)[\"']{re.escape(str(key))}[\"']\s*:\s*"
#     match = re.search(key_pattern, block)
#
#     if match:
#         value_start = match.end()
#         depth_square = 0
#         depth_curly = 0
#         quote = None
#         escape = False
#         value_end = None
#         for offset in range(value_start, len(block)):
#             char = block[offset]
#             if quote:
#                 if escape:
#                     escape = False
#                 elif char == "\\":
#                     escape = True
#                 elif char == quote:
#                     quote = None
#                 continue
#             if char in ("'", '"'):
#                 quote = char
#             elif char == "[":
#                 depth_square += 1
#             elif char == "]":
#                 depth_square -= 1
#             elif char == "{":
#                 depth_curly += 1
#             elif char == "}":
#                 depth_curly -= 1
#             elif char == "," and depth_square == 0 and depth_curly == 0:
#                 value_end = offset + 1
#                 break
#         if value_end is None:
#             raise ValueError(f"cannot find end of entry {key} in {marker}")
#         indent = match.group("indent")
#         replacement = f'{indent}"{key}": {value_text},'
#         new_block = block[:match.start()] + replacement + block[value_end:]
#     else:
#         insert_at = len(block) - 1
#         new_block = block[:insert_at] + f'  "{key}": {value_text},\n' + block[insert_at:]
#
#     return text[:start] + new_block + text[end + 1:]
#
#
# def _format_intersection_rid_list(rid_list):
#     if not rid_list:
#         return "[]"
#     return _format_python_literal(
#         [(row["rid"], row["direction"]) for row in rid_list]
#     )
#
#
# def _format_online_data_map(online_data_map):
#     formatted = {rid: {} for rid in sorted(online_data_map.keys())}
#     return _format_python_literal(formatted)
#
#
# def _replace_brace_block(text, marker, new_block):
#     start, end = _find_brace_block(text, marker)
#     return text[:start] + new_block + text[end + 1:]
#
#
# def _ensure_online_data_map_rids(text, rid_list):
#     online_data_map = _load_python_assignment_from_text(text, "online_data_map_lambda")
#     changed = []
#     for row in rid_list:
#         rid = row["rid"]
#         if rid in online_data_map:
#             continue
#         online_data_map[rid] = {}
#         changed.append(rid)
#     if changed:
#         text = _replace_assignment_in_text(
#             text,
#             "online_data_map_lambda",
#             _format_online_data_map(online_data_map) + ".copy()",
#         )
#     return text, changed
#
#
# def _update_lambdas_online_config(cross_id, rid_list, dry_run):
#     text = _read_text(LAMBDAS_PATH)
#     text = _replace_mapping_entry(
#         text,
#         "intersection_to_rid_lambda",
#         cross_id,
#         _format_intersection_rid_list(rid_list),
#     )
#     text, added_rids = _ensure_online_data_map_rids(text, rid_list)
#     if not dry_run:
#         _write_text(LAMBDAS_PATH, text)
#     return {
#         "path": _rel_path(LAMBDAS_PATH),
#         "intersection_to_rid_lambda": "updated",
#         "online_data_map_lambda_added_rids": added_rids,
#     }
#
#
# def _ensure_global_online_cross_id(text, cross_id_int):
#     start, end = _find_brace_block(text, "intern_road_id=")
#     block = text[start:end + 1]
#     if re.search(rf"(?<!\d){cross_id_int}(?!\d)", block):
#         return text, False
#     new_block = block[:-1] + f"{cross_id_int},\n" + block[-1:]
#     return text[:start] + new_block + text[end + 1:], True
#
#
# def _online_mapping_to_dict(mapping):
#     if isinstance(mapping, dict):
#         return dict(mapping)
#     normalized = {}
#     if isinstance(mapping, list):
#         for index in range(0, len(mapping) - 1, 2):
#             raw_cross_id = mapping[index]
#             direction = mapping[index + 1]
#             if str(raw_cross_id) == "0":
#                 continue
#             key = int(raw_cross_id) if str(raw_cross_id).isdigit() else raw_cross_id
#             normalized[key] = direction
#     return normalized
#
#
# def _mapping_contains_cross(mapping, cross_id_int):
#     if isinstance(mapping, dict):
#         return cross_id_int in mapping or str(cross_id_int) in mapping
#     if isinstance(mapping, list):
#         for index in range(0, len(mapping) - 1, 2):
#             if str(mapping[index]) == str(cross_id_int):
#                 return True
#     return False
#
#
# def _update_online_map_info(text, cross_id_int, rid_list):
#     start, end = _find_brace_block(text, "online_map_info =")
#     block = text[start:end + 1]
#     online_map_info = ast.literal_eval(block)
#
#     old_rids_for_cross = {
#         rid for rid, mapping in online_map_info.items()
#         if _mapping_contains_cross(mapping, cross_id_int)
#     }
#     new_rids = {row["rid"] for row in rid_list}
#     for rid in old_rids_for_cross - new_rids:
#         mapping = _online_mapping_to_dict(online_map_info.get(rid))
#         mapping.pop(cross_id_int, None)
#         mapping.pop(str(cross_id_int), None)
#         if mapping:
#             online_map_info[rid] = mapping
#         else:
#             online_map_info.pop(rid, None)
#
#     for row in rid_list:
#         mapping = _online_mapping_to_dict(online_map_info.get(row["rid"]))
#         mapping[cross_id_int] = row["direction"]
#         online_map_info[row["rid"]] = mapping
#
#     lines = ["{"]
#     for rid in sorted(online_map_info.keys()):
#         lines.append(f"{rid!r}: {online_map_info[rid]!r},")
#     lines.append("}")
#     new_block = "\n".join(lines)
#     return text[:start] + new_block + text[end + 1:]
#
#
# def _update_global_online_config(cross_id_int, rid_list, dry_run):
#     text = _read_text(GLOBAL_COORDINATE_PATH)
#     text, added_cross_id = _ensure_global_online_cross_id(text, cross_id_int)
#     text = _update_online_map_info(text, cross_id_int, rid_list)
#     if not dry_run:
#         _write_text(GLOBAL_COORDINATE_PATH, text)
#     return {
#         "path": _rel_path(GLOBAL_COORDINATE_PATH),
#         "intern_road_id": "created" if added_cross_id else "exists",
#         "online_map_info": "updated",
#     }
#
#
# def validate_and_save_online_intersection_config(payload, dry_run=False):
#     try:
#         item = _normalize_online_intersection_payload(payload)
#         result = {
#             "code": 0,
#             "status": "validated" if dry_run else "success",
#             "saved": not dry_run,
#             "message": "validation success" if dry_run else "save success",
#             "Cross_id": item["cross_id"],
#             "rid_list": item["rid_list"],
#             "display_after_save": {
#                 "method": "GET",
#                 "url": f"/online_intersection_config?Cross_id={item['cross_id']}",
#                 "frontend_target": "refresh detail table from response.rid_list",
#             },
#             "code_changes": {},
#         }
#         with _write_lock:
#             result["code_changes"]["Lambdas.py"] = _update_lambdas_online_config(
#                 item["cross_id"], item["rid_list"], dry_run
#             )
#             result["code_changes"]["Global_intersection_coordinate.py"] = (
#                 _update_global_online_config(
#                     item["cross_id_int"], item["rid_list"], dry_run
#                 )
#             )
#         return result
#     except Exception as error:
#         return {
#             "code": 1,
#             "status": "error",
#             "saved": False,
#             "reason": str(error),
#         }
#
#
# def delete_online_intersection_config(payload, dry_run=False):
#     try:
#         if not isinstance(payload, dict):
#             raise ValueError("payload must be a JSON object")
#         cross_id = _normalize_key(_get_any(payload, "Cross_id", "cross_id", "CrossID"))
#         if not cross_id.isdigit():
#             raise ValueError("Cross_id must be numeric")
#
#         empty_payload = {
#             "Cross_id": cross_id,
#             "rid_list": [],
#         }
#         result = validate_and_save_online_intersection_config(empty_payload, dry_run=dry_run)
#         if result.get("status") != "error":
#             result["message"] = "validation success" if dry_run else "delete success"
#             result["operation"] = "deleted"
#             result["display_after_save"] = {
#                 "method": "GET",
#                 "url": f"/online_intersection_config?Cross_id={cross_id}",
#                 "frontend_target": "refresh detail table; rid_list will be empty",
#             }
#         return result
#     except Exception as error:
#         return {
#             "code": 1,
#             "status": "error",
#             "saved": False,
#             "reason": str(error),
#         }
#
#
# def _without_road_info(payload):
#     if not isinstance(payload, dict):
#         return payload
#     copied = copy.deepcopy(payload)
#     copied.pop("road_info", None)
#     if isinstance(copied.get("items"), list):
#         for item in copied["items"]:
#             if isinstance(item, dict):
#                 item.pop("road_info", None)
#     return copied
#
#
# def validate_and_save_cross_info_config(payload, dry_run=False):
#     return validate_and_save_intersection_config(_without_road_info(payload), dry_run=dry_run)
#
#
# def get_cross_info_config(cross_id):
#     cross_key = _normalize_key(cross_id)
#     cross_data = _read_json(CROSS_INFO_PATH)
#     return {
#         "Cross_id": cross_key,
#         "file": _rel_path(CROSS_INFO_PATH),
#         "cross_info": copy.deepcopy(cross_data.get(cross_key)),
#         "code_config_options": _frontend_code_config_options(),
#     }
#
#
# def list_cross_info_configs(full=False):
#     cross_data = _read_json(CROSS_INFO_PATH)
#     result = {
#         "status": "success",
#         "file": _rel_path(CROSS_INFO_PATH),
#         "count": len(cross_data),
#         "cross_ids": sorted(cross_data.keys(), key=str),
#         "code_config_options": _frontend_code_config_options(),
#     }
#     if full:
#         result["cross_info"] = cross_data
#     return result
#
#
# def delete_cross_info_config(payload, dry_run=False):
#     if isinstance(payload, dict):
#         copied = copy.deepcopy(payload)
#     else:
#         copied = payload
#     if isinstance(copied, dict):
#         copied["delete_road_info"] = False
#         copied.setdefault("delete_cross_info", True)
#         copied.setdefault("delete_code", True)
#     return delete_intersection_config(copied, dry_run=dry_run)
#
#
# def delete_intersection_config(payload, dry_run=False):
#     try:
#         if not isinstance(payload, dict):
#             raise ValueError("payload must be a JSON object")
#         cross_id = _normalize_key(_get_any(payload, "Cross_id", "cross_id", "CrossID"))
#         if not cross_id.isdigit():
#             raise ValueError("Cross_id must be numeric")
#
#         delete_road_info = bool(payload.get("delete_road_info", True))
#         delete_cross_info = bool(payload.get("delete_cross_info", True))
#         delete_code = bool(payload.get("delete_code", True))
#         code_config = _normalize_code_config(payload)
#
#         result = {
#             "status": "validated" if dry_run else "success",
#             "saved": not dry_run,
#             "message": "validation success" if dry_run else "delete success",
#             "Cross_id": cross_id,
#             "files": {},
#             "code_changes": {},
#         }
#
#         with _write_lock:
#             existing_cross_info = None
#
#             if delete_road_info:
#                 road_data = _read_json(ROAD_INFO_PATH)
#                 existed = cross_id in road_data
#                 result["files"]["road_info.json"] = {
#                     "path": _rel_path(ROAD_INFO_PATH),
#                     "operation": "deleted" if existed else "not_found",
#                 }
#                 if existed and not dry_run:
#                     del road_data[cross_id]
#                     _write_json(ROAD_INFO_PATH, road_data)
#
#             if delete_cross_info:
#                 cross_data = _read_json(CROSS_INFO_PATH)
#                 existing_cross_info = copy.deepcopy(cross_data.get(cross_id))
#                 existed = cross_id in cross_data
#                 result["files"]["cross_info.json"] = {
#                     "path": _rel_path(CROSS_INFO_PATH),
#                     "operation": "deleted" if existed else "not_found",
#                 }
#                 if existed and not dry_run:
#                     del cross_data[cross_id]
#                     _write_json(CROSS_INFO_PATH, cross_data)
#             else:
#                 existing_cross_info = _read_json(CROSS_INFO_PATH).get(cross_id)
#
#             if delete_code and code_config["enabled"]:
#                 if code_config["update_lambdas"]:
#                     result["code_changes"]["Lambdas.py"] = _remove_lambdas_file(
#                         cross_id,
#                         existing_cross_info,
#                         code_config,
#                         dry_run,
#                     )
#                 if code_config["update_global"]:
#                     result["code_changes"]["Global_intersection_coordinate.py"] = (
#                         _remove_global_coordinate_file(cross_id, code_config, dry_run)
#                     )
#                 if code_config["update_dqn"]:
#                     result["code_changes"]["DQN_Select.py"] = _remove_dqn_select_file(
#                         cross_id,
#                         dry_run,
#                     )
#
#         return result
#     except Exception as error:
#         return {
#             "status": "error",
#             "saved": False,
#             "reason": str(error),
#         }
#
#
# def _normalize_day_type(payload):
#     raw = _get_any(payload, "day_type", "Day_type", "type")
#     is_work_day = _get_any(payload, "is_workday", "is_work_day", "IS_work_day")
#     target_date = _get_any(payload, "date", "target_date")
#
#     if isinstance(raw, str):
#         value = raw.strip().lower()
#         if value in ("workday", "weekday", "yes", "true"):
#             return "workday"
#         if value in ("weekend", "holiday", "no", "false"):
#             return "weekend"
#
#     if isinstance(is_work_day, bool):
#         return "workday" if is_work_day else "weekend"
#     if isinstance(is_work_day, str):
#         value = is_work_day.strip().lower()
#         if value in ("yes", "true", "1", "workday", "weekday"):
#             return "workday"
#         if value in ("no", "false", "0", "weekend", "holiday"):
#             return "weekend"
#
#     if target_date:
#         parsed = datetime.strptime(str(target_date), "%Y-%m-%d").date()
#         if _is_workday is not None:
#             return "workday" if _is_workday(parsed) else "weekend"
#         return "workday" if parsed.weekday() < 5 else "weekend"
#
#     today = date.today()
#     if _is_workday is not None:
#         return "workday" if _is_workday(today) else "weekend"
#     return "workday" if today.weekday() < 5 else "weekend"
#
#
# def _normalize_schedule(schedule):
#     if not isinstance(schedule, dict) or not schedule:
#         raise ValueError("schedule must be a non-empty JSON object")
#     normalized = {}
#     for hour, values in schedule.items():
#         hour_key = _normalize_key(hour)
#         if not hour_key.isdigit() or not 0 <= int(hour_key) <= 23:
#             raise ValueError(f"invalid schedule hour: {hour_key}")
#         if not isinstance(values, list) or len(values) != 10:
#             raise ValueError(f"schedule[{hour_key}] must be a list of length 10")
#         normalized[hour_key] = values
#     return normalized
#
#
# def _extract_schedule_payload(payload):
#     schedule = _get_any(payload, "schedule", "Time_schedule")
#     if schedule is not None:
#         return schedule
#
#     direct_schedule = {
#         key: value for key, value in payload.items()
#         if str(key).isdigit() and 0 <= int(str(key)) <= 23
#     }
#     if direct_schedule:
#         return direct_schedule
#     return None
#
#
# def _schedule_path(cross_id, day_type):
#     prefix = "Time_schedule_" if day_type == "workday" else "Time_schedule_weekend_"
#     return os.path.join(SCHEDULE_JSON_DIR, f"{prefix}{cross_id}.json")
#
#
# def _normalize_delete_day_types(payload):
#     raw = _get_any(payload, "day_type", "Day_type", "type", default="workday")
#     if isinstance(raw, str) and raw.strip().lower() in ("both", "all"):
#         return ["workday", "weekend"]
#     return [_normalize_day_type(payload)]
#
#
# def validate_and_save_schedule_config(payload, dry_run=False):
#     try:
#         if not isinstance(payload, dict):
#             raise ValueError("payload must be a JSON object")
#         cross_id = _normalize_key(_get_any(payload, "Cross_id", "cross_id", "CrossID"))
#         if not cross_id.isdigit():
#             raise ValueError("Cross_id must be numeric")
#         day_type = _normalize_day_type(payload)
#         schedule = _normalize_schedule(_extract_schedule_payload(payload))
#         path = _schedule_path(cross_id, day_type)
#
#         result = {
#             "status": "validated" if dry_run else "success",
#             "saved": not dry_run,
#             "message": "validation success" if dry_run else "save success",
#             "Cross_id": cross_id,
#             "day_type": day_type,
#             "file": _rel_path(path),
#             "operation": "updated" if os.path.exists(path) else "created",
#         }
#         if not dry_run:
#             with _write_lock:
#                 _write_json(path, schedule)
#         return result
#     except Exception as error:
#         return {
#             "status": "error",
#             "saved": False,
#             "reason": str(error),
#         }
#
#
# def get_schedule_config(cross_id, day_type="workday"):
#     cross_key = _normalize_key(cross_id)
#     normalized_day_type = "weekend" if str(day_type).lower() in ("weekend", "holiday") else "workday"
#     path = _schedule_path(cross_key, normalized_day_type)
#     return {
#         "Cross_id": cross_key,
#         "day_type": normalized_day_type,
#         "file": _rel_path(path),
#         "schedule": _read_json(path) if os.path.exists(path) else None,
#     }
#
#
# def delete_schedule_config(payload, dry_run=False):
#     try:
#         if not isinstance(payload, dict):
#             raise ValueError("payload must be a JSON object")
#         cross_id = _normalize_key(_get_any(payload, "Cross_id", "cross_id", "CrossID"))
#         if not cross_id.isdigit():
#             raise ValueError("Cross_id must be numeric")
#
#         day_types = _normalize_delete_day_types(payload)
#         files = []
#         with _write_lock:
#             for day_type in day_types:
#                 path = _schedule_path(cross_id, day_type)
#                 existed = os.path.exists(path)
#                 files.append({
#                     "day_type": day_type,
#                     "file": _rel_path(path),
#                     "operation": "deleted" if existed else "not_found",
#                 })
#                 if existed and not dry_run:
#                     os.remove(path)
#
#         return {
#             "status": "validated" if dry_run else "success",
#             "saved": not dry_run,
#             "message": "validation success" if dry_run else "delete success",
#             "Cross_id": cross_id,
#             "files": files,
#         }
#     except Exception as error:
#         return {
#             "status": "error",
#             "saved": False,
#             "reason": str(error),
#         }
