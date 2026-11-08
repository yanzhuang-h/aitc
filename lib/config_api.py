"""轻量配置接口：road_info / cross_info_config / intersection_schedule /
online_intersection_config / floating_value。

路由约定与《流量路口配置接口信息》《online 路口配置》《floating_value 接口需求》
一致：先 validate（saved=false，不落盘），再 update（saved=true）；
失败统一返回 status=error + reason。
"""

from urllib.parse import parse_qs, unquote, urlparse

from lib import cross_info_functions as cross_info
from lib import online_intersection_config as online_config
from lib import road_info_functions as road_info
from lib import schedule_functions as schedule
from lib.floating_value import validate_and_save_floating_value


_RESOURCES = {
    "road_info",
    "cross_info_config",
    "cross_info",
    "intersection_schedule",
    "online_intersection_config",
    "floating_value",
}

_CROSS_ALIASES = {"cross_info_config", "cross_info"}


def _error(reason):
    return {
        "status": "error",
        "saved": False,
        "reason": str(reason),
    }


def _segments(path):
    parsed = urlparse(path or "")
    parts = [
        unquote(segment)
        for segment in parsed.path.strip("/").split("/")
        if segment
    ]
    query = parse_qs(parsed.query)
    return parts, query


def _flag(query, name, default=False):
    raw = (query.get(name) or [""])[0]
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _first(query, name, default=None):
    values = query.get(name) or []
    return values[0] if values else default


def _road_info_get(segments, query):
    if len(segments) == 1:
        return 200, road_info.list_road_infos(full=_flag(query, "full"))
    if len(segments) == 2:
        return 200, road_info.query_road_info({"Cross_id": segments[1]})
    return 404, _error("unknown road_info endpoint")


def _cross_info_get(segments, query):
    if len(segments) == 1:
        return 200, cross_info.list_cross_infos(full=_flag(query, "full"))
    if len(segments) == 2:
        return 200, cross_info.query_cross_info({"Cross_id": segments[1]})
    return 404, _error("unknown cross_info endpoint")


def _schedule_get(segments, query):
    if len(segments) != 2:
        return 404, _error("unknown intersection_schedule endpoint")
    day_type = _first(query, "day_type", "workday")
    return 200, schedule.query_schedule(segments[1], day_type)


def _online_get(segments, query):
    if len(segments) == 1:
        cross_id = _first(query, "Cross_id")
        if cross_id:
            return 200, online_config.get_online_config(cross_id)
        return 200, {
            "code": 0,
            "status": "success",
            "items": online_config.list_online_configs(),
        }
    if len(segments) == 2:
        return 200, online_config.get_online_config(segments[1])
    return 404, _error("unknown online_intersection_config endpoint")


def _handle_get(segments, query):
    resource = segments[0]
    if resource == "road_info":
        return _road_info_get(segments, query)
    if resource in _CROSS_ALIASES:
        return _cross_info_get(segments, query)
    if resource == "intersection_schedule":
        return _schedule_get(segments, query)
    if resource == "online_intersection_config":
        return _online_get(segments, query)
    if resource == "floating_value":
        return 404, _error("floating_value only supports POST validate/update")
    return 404, _error("unknown config resource")


def _post_road_info(segments, body):
    action = segments[1]
    if action == "validate":
        return road_info.validate_and_save_road_info(body, dry_run=True)
    if action == "update":
        return road_info.validate_and_save_road_info(body, dry_run=False)
    if action == "add":
        return road_info.add_road_info(body)
    if action == "delete":
        cross_id = (body or {}).get("Cross_id")
        return road_info.delete_road_info(cross_id, dry_run=_flag_obj(body, "dry_run"))
    return None


def _post_cross_info(segments, body):
    action = segments[1]
    if action == "validate":
        return cross_info.validate_and_save_cross_info(body, dry_run=True)
    if action == "update":
        return cross_info.validate_and_save_cross_info(body, dry_run=False)
    if action == "add":
        return cross_info.add_cross_info(body)
    if action == "delete":
        payload = body or {}
        return cross_info.delete_cross_info(
            payload.get("Cross_id"),
            dry_run=_flag_obj(payload, "dry_run"),
            delete_code=payload.get("delete_code", True) is not False,
        )
    return None


def _flag_obj(payload, name):
    if not isinstance(payload, dict):
        return False
    value = payload.get(name, False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _post_schedule(segments, body):
    action = segments[1]
    if action == "validate":
        return schedule.validate_and_save_schedule(body, dry_run=True)
    if action == "update":
        return schedule.validate_and_save_schedule(body, dry_run=False)
    if action == "delete":
        payload = body or {}
        return schedule.delete_schedule(
            payload.get("Cross_id"),
            payload.get("day_type", "workday"),
            dry_run=_flag_obj(payload, "dry_run"),
        )
    return None


def _post_online(segments, body):
    if segments[1] != "update":
        return None
    return online_config.validate_and_save_online_config(
        body, dry_run=_flag_obj(body or {}, "dry_run")
    )


def _post_floating(segments, body):
    if segments[1] not in ("validate", "update"):
        return None
    return validate_and_save_floating_value(
        body, dry_run=segments[1] == "validate"
    )


def _handle_post(segments, body):
    if len(segments) != 2:
        return 404, _error("unknown config endpoint")
    resource = segments[0]
    handlers = {
        "road_info": _post_road_info,
        "cross_info_config": _post_cross_info,
        "cross_info": _post_cross_info,
        "intersection_schedule": _post_schedule,
        "online_intersection_config": _post_online,
        "floating_value": _post_floating,
    }
    handler = handlers.get(resource)
    if handler is None:
        return 404, _error("unknown config resource")
    if not isinstance(body, dict):
        return 400, _error("request body must be a JSON object")
    result = handler(segments, body)
    if result is None:
        return 404, _error("unknown config endpoint")
    status_code = 200 if result.get("status") != "error" else 400
    return status_code, result


def _handle_delete(segments, query):
    if len(segments) != 2:
        return 404, _error("unknown config endpoint")
    resource, cross_id = segments
    dry_run = _flag(query, "dry_run")

    if resource == "road_info":
        result = road_info.delete_road_info(cross_id, dry_run=dry_run)
    elif resource in _CROSS_ALIASES:
        result = cross_info.delete_cross_info(
            cross_id,
            dry_run=dry_run,
            delete_code=_flag(query, "delete_code", True),
        )
    elif resource == "intersection_schedule":
        result = schedule.delete_schedule(
            cross_id,
            _first(query, "day_type", "workday"),
            dry_run=dry_run,
        )
    elif resource == "online_intersection_config":
        result = online_config.delete_online_config(cross_id, dry_run=dry_run)
    else:
        return 404, _error("unknown config resource")

    status_code = 200 if result.get("status") != "error" else 400
    return status_code, result


def handle_config_request(method, path, body=None):
    """Route configuration requests.

    Returns ``(status_code, payload)`` for configuration paths and ``None``
    for paths owned by other handlers.
    """
    segments, query = _segments(path)
    if not segments or segments[0] not in _RESOURCES:
        return None

    method = str(method).upper()
    if method == "GET":
        return _handle_get(segments, query)
    if method == "POST":
        return _handle_post(segments, body)
    if method == "DELETE":
        return _handle_delete(segments, query)
    return 405, _error(f"method {method} not allowed")
