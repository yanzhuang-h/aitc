"""互联网路口 RID 方向配置（整体覆盖保存）。

对应文档「online 路口配置」：
    GET  /online_intersection_config?Cross_id=1100308
    GET  /online_intersection_config
    POST /online_intersection_config/update

配置写入 lib/online_intersection_config.json，运行时由 Lambdas
优先读取该文件、缺省回退到代码内置映射，因此编译发布后仍然可改。
"""

import copy
import json
import os
import tempfile

from lib._local_json_store import read_json_object, write_json_object


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ONLINE_CONFIG_PATH = os.path.join(BASE_DIR, "online_intersection_config.json")


def _normalize_cross_id(value):
    if value is None or isinstance(value, bool):
        raise ValueError("Cross_id is required")
    cross_id = str(value).strip()
    if not cross_id.isdigit():
        raise ValueError("Cross_id must be numeric")
    return cross_id


def _normalize_rid_list(value):
    if not isinstance(value, list):
        raise ValueError("rid_list must be a list")

    normalized = []
    seen = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"rid_list[{index}] must be a JSON object")
        rid = str(item.get("rid", "") or "").strip()
        direction = str(item.get("direction", "") or "").strip()
        if not rid:
            raise ValueError(f"rid_list[{index}].rid is required")
        if not direction:
            raise ValueError(f"rid_list[{index}].direction is required")
        if rid in seen:
            raise ValueError(f"duplicated rid: {rid}")
        seen.add(rid)
        normalized.append({"rid": rid, "direction": direction})
    return normalized


def _file_label():
    return os.path.relpath(ONLINE_CONFIG_PATH, os.path.dirname(BASE_DIR)).replace(os.sep, "/")


def load_online_overrides():
    """读取 online 覆盖配置；文件不存在时返回空表。"""
    try:
        return read_json_object(ONLINE_CONFIG_PATH)
    except (OSError, ValueError):
        return {}


def _default_rows(cross_id):
    """代码内置的 RID 映射（发布包中由 Lambdas 提供）。"""
    try:
        from Lambdas import intersection_to_rid_lambda
    except Exception:
        return []
    return [
        {"rid": str(rid), "direction": str(direction)}
        for rid, direction in intersection_to_rid_lambda.get(str(cross_id), [])
    ]


def get_online_config(cross_id):
    cross_id = _normalize_cross_id(cross_id)
    data = load_online_overrides()
    rows = data.get(cross_id)
    if rows is None:
        rows = _default_rows(cross_id)
    return {
        "code": 0,
        "status": "success",
        "Cross_id": cross_id,
        "rid_list": copy.deepcopy(rows),
    }


def list_online_configs():
    data = load_online_overrides()
    cross_ids = set(data)
    try:
        from Lambdas import intersection_to_rid_lambda
        cross_ids.update(str(cross_id) for cross_id in intersection_to_rid_lambda)
    except Exception:
        pass

    items = []
    for cross_id in sorted(cross_ids):
        rows = data.get(cross_id)
        if rows is None:
            rows = _default_rows(cross_id)
        items.append({
            "code": 0,
            "status": "success",
            "Cross_id": cross_id,
            "rid_list": copy.deepcopy(rows),
        })
    return items


def validate_and_save_online_config(payload, dry_run=False):
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        cross_id = _normalize_cross_id(payload.get("Cross_id"))
        rid_list = _normalize_rid_list(payload.get("rid_list"))

        if not dry_run:
            data = load_online_overrides()
            data[cross_id] = rid_list
            write_json_object(ONLINE_CONFIG_PATH, data)

        return {
            "code": 0,
            "status": "validated" if dry_run else "success",
            "saved": not dry_run,
            "message": "validation success" if dry_run else "save success",
            "Cross_id": cross_id,
            "file": _file_label(),
            "display_after_save": {
                "method": "GET",
                "url": f"/online_intersection_config?Cross_id={cross_id}",
                "frontend_target": "refresh detail table from response.rid_list",
            },
        }
    except Exception as error:
        return {
            "code": 1,
            "status": "error",
            "saved": False,
            "reason": str(error),
        }


def delete_online_config(cross_id, dry_run=False):
    try:
        cross_id = _normalize_cross_id(cross_id)
        data = load_online_overrides()
        existed = cross_id in data
        if existed and not dry_run:
            del data[cross_id]
            write_json_object(ONLINE_CONFIG_PATH, data)

        return {
            "code": 0,
            "status": "validated" if dry_run else "success",
            "saved": not dry_run,
            "deleted": existed,
            "Cross_id": cross_id,
            "file": _file_label(),
        }
    except Exception as error:
        return {
            "code": 1,
            "status": "error",
            "saved": False,
            "reason": str(error),
        }
