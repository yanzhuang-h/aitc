"""路口运行策略；上线批次只用于标注，策略由本地onboard登记。"""

import json
from pathlib import Path

from lib.platform_registration import registered_platform_programs
from lib.road_groups import TONGZHOU_19

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


def supports_online_experience_growth(road_id):
    """19组及本地登记的平台路口允许新增达标经验点，不改变相位策略。"""
    return str(road_id) in TONGZHOU_19 or uses_platform_phase_timing(road_id)


def _load_plan_overrides():
    try:
        stat = _PLAN_OVERRIDES_PATH.stat()
    except OSError:
        return {}
    signature = (str(_PLAN_OVERRIDES_PATH), stat.st_mtime_ns, stat.st_size)
    if signature != _PLAN_OVERRIDES_CACHE["signature"]:
        try:
            data = json.loads(_PLAN_OVERRIDES_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        _PLAN_OVERRIDES_CACHE["data"] = data if isinstance(data, dict) else {}
        _PLAN_OVERRIDES_CACHE["signature"] = signature
    return _PLAN_OVERRIDES_CACHE["data"]


PLATFORM_ROAD_PROGRAMS = registered_platform_programs(_load_plan_overrides())
PLATFORM_PHASE_ROAD_IDS |= frozenset(PLATFORM_ROAD_PROGRAMS)


def program_id_override(road_id, default=None):
    """读取现有方案号覆盖或单文件登记中的默认方案号。"""
    entry = _load_plan_overrides().get(str(road_id), default)
    return entry.get("program_id", default) if isinstance(entry, dict) else entry


def resolve_output_program_id(road_id, program_id):
    """平台已选中的非零方案优先，其余沿用本地方案号映射。"""
    if uses_platform_phase_timing(road_id) and type(program_id) is int and program_id > 0:
        return program_id
    return program_id_override(road_id, program_id)
