from urllib.parse import unquote

from lib.cross_info_functions import (
    add_cross_info,
    query_cross_info,
    update_cross_info,
)
from lib.road_info_functions import (
    add_road_info,
    query_road_info,
    update_road_info,
)


_RESOURCES = {
    "road_info": {
        "query": query_road_info,
        "add": add_road_info,
        "update": update_road_info,
    },
    "cross_info": {
        "query": query_cross_info,
        "add": add_cross_info,
        "update": update_cross_info,
    },
}


def _error(reason):
    return {
        "status": "error",
        "saved": False,
        "reason": reason,
    }


def _path_segments(path):
    if not isinstance(path, str):
        return []
    return [
        unquote(segment)
        for segment in path.split("?", 1)[0].strip("/").split("/")
        if segment
    ]


def handle_config_request(method, path, body=None):
    """Route the lightweight road/cross JSON configuration API.

    Returns ``(status_code, payload)`` for configuration paths and ``None``
    for paths owned by the radar/health handler.
    """
    segments = _path_segments(path)
    if not segments or segments[0] not in _RESOURCES:
        return None

    resource_name = segments[0]
    resource = _RESOURCES[resource_name]
    method = str(method).upper()

    if method == "GET":
        if len(segments) != 2:
            return 404, _error(f"unknown {resource_name} endpoint")

        cross_id = segments[1].strip()
        if not cross_id.isdigit():
            return 400, _error("Cross_id must be numeric")

        return 200, resource["query"]({"Cross_id": cross_id})

    if method == "POST":
        if len(segments) != 2 or segments[1] not in ("add", "update"):
            return 404, _error(f"unknown {resource_name} endpoint")
        if not isinstance(body, dict):
            return 400, _error("request body must be a JSON object")

        result = resource[segments[1]](body)
        status_code = 200 if result.get("status") == "success" else 400
        return status_code, result

    return 405, _error(f"method {method} is not allowed")
