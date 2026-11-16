"""路口运行策略；上线批次只用于标注，策略由本地onboard登记。"""

import json
from pathlib import Path

PLATFORM_PHASE_ROAD_IDS = frozenset({
    "1700035",
    "1700062",
    "1700151",
    "1700240",
    "1700267",
    "1700269",
    "1700311",
    "1700312",
    "1700314",
    "1700315",
    "1700345",
    "1700347",
    "1700348",
    "1700451",
    "1700452",
    "1700453",
    "1700454",
    "1700455",
    "1700456",
    "1700544",
    "1700546",
    "1700548",
    "1700549",
    "1700553",
    "1700555",
    "1700556",
    "2703310",
    "2703314",
    "2703317",
    "2703318",
    "2703320",
    "2703491",
    "2703802",
    "2704257",
    "2704740",
    "2704746",
    "2705189",
    "2705192",
    "2705194",
    "2706110",
    "2706134",
    "2706149",
    "2706150",
    "2706152",
    "2706537",
    "2706540",
    "2707788",
    "2709471",
    "2710273",
})

_PLAN_OVERRIDES_PATH = Path(__file__).resolve().parent / "plan_id_overrides.json"
_PLAN_OVERRIDES_CACHE = {"signature": None, "data": {}}


def uses_platform_phase_timing(road_id):
    return str(road_id) in PLATFORM_PHASE_ROAD_IDS


def program_id_override(road_id, default=None):
    """选择器与发送器读取同一本地方案号配置。"""
    try:
        stat = _PLAN_OVERRIDES_PATH.stat()
    except OSError:
        return default
    signature = (str(_PLAN_OVERRIDES_PATH), stat.st_mtime_ns, stat.st_size)
    if signature != _PLAN_OVERRIDES_CACHE["signature"]:
        try:
            data = json.loads(_PLAN_OVERRIDES_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        _PLAN_OVERRIDES_CACHE["data"] = data if isinstance(data, dict) else {}
        _PLAN_OVERRIDES_CACHE["signature"] = signature
    return _PLAN_OVERRIDES_CACHE["data"].get(str(road_id), default)
