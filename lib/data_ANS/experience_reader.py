"""读取运行经验：历史底表保留，发布在线点按方向和秒数覆盖。"""

import json
import os
from pathlib import Path
import threading

from app.paths import EXPERIENCE_POOL_DIR
from lib.intersection_strategy import uses_platform_phase_timing

DEFAULT_EXPERIENCE_PATH = EXPERIENCE_POOL_DIR / "online_experience.json"
_JSON_CACHE = {}
_CACHE_LOCK = threading.Lock()


def runtime_experience_path(default_path=DEFAULT_EXPERIENCE_PATH):
    """显式分配器表优先，其次日常学习发布路径，最后默认共享目录。"""
    return Path(os.environ.get("AITC_FLOW_ALLOCATOR_SHADOW_TABLE")
                or os.environ.get("AITC_EXPERIENCE_RUNTIME_TABLE")
                or default_path).resolve()


def load_json_cached(path):
    path = Path(path).resolve()
    stat = path.stat()
    version = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
    with _CACHE_LOCK:
        cached = _JSON_CACHE.get(path)
        if cached and cached["version"] == version:
            return cached["data"]
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise TypeError(f"经验或配置 JSON 根节点须为对象: {path}")
        _JSON_CACHE[path] = {"version": version, "data": data}
        return data


def _optional_table(path, *, missing_ok=True):
    try:
        return load_json_cached(path)
    except FileNotFoundError:
        if not missing_ok:
            raise
        return {}


def load_experience_table(*, offline_path=None, online_path=None, road_id=None, include_online=True):
    """只读发布运行表；零是有效值，整条车道向量覆盖，不按非零猜测来源。

    在线候选和经验池样本不是发布表，禁止从它们即时拼接配时数据。
    平台相位策略只读取在线经验；历史算法保留各自指定的离线底表；
    include_online=False 保留旧算法回退路径，不提前切换全部历史路口。
    """
    road_id = None if road_id is None else str(road_id)
    online = (_optional_table(
        online_path if online_path is not None else runtime_experience_path(),
        missing_ok=offline_path is not None or (road_id is not None and uses_platform_phase_timing(road_id)),
    ) if include_online else {})
    # 单路口平台请求不访问离线文件，空表也可正常进入既有冷启动兜底。
    offline = (_optional_table(offline_path) if offline_path is not None
               and (road_id is None or not uses_platform_phase_timing(road_id)) else {})
    roads = set(offline) | set(online) if road_id is None else {road_id}
    result = {}
    for road in roads:
        base = {} if uses_platform_phase_timing(road) else offline.get(road, {})
        live = online.get(road, {})
        if road not in online and not base:
            continue
        result[road] = {}
        for direction in base.keys() | live.keys():
            points = {**base.get(direction, {}), **live.get(direction, {})}
            # 旧算法按字典顺序查表，发布 JSON 的字典序不能决定绿灯秒数。
            result[road][direction] = {second: list(points[second])
                                       for second in sorted(points, key=int)}
    return result
