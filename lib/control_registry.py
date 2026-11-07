"""路口控制注册表：路口 ID + 四方向摄像头（道路编码）。

技术闸门：只有登记且 ``enabled`` 的路口才允许在线分配器接管；
未登记的路口继续走原逻辑，不改变现有配时行为。

注册表由我方维护（运维无法自行生成），格式见 ``lib/control_registry.json``：

    {
      "schema_version": 1,
      "roads": {
        "1700542": {
          "enabled": true,
          "cameras": {"R": "110073", "D": "110074", "L": "110075", "U": "110076"}
        }
      }
    }

方向按 LRUD 约定：U=北向南，D=南向北，L=西向东，R=东向西。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

DEFAULT_PATH = Path(__file__).with_name("control_registry.json")
CAMERA_DIRECTIONS = ("U", "D", "L", "R")

_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[tuple[int, int], dict[str, "RoadRegistration"]]] = {}


class ControlRegistryError(ValueError):
    """注册表缺失或内容非法。"""


@dataclass(frozen=True)
class RoadRegistration:
    """一个路口的登记信息。"""

    road_id: str
    enabled: bool = False
    cameras: dict[str, str] = field(default_factory=dict)
    profile: str | None = None


def _registry_path(path: str | os.PathLike | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("AITC_CONTROL_REGISTRY", "").strip()
    return Path(configured) if configured else DEFAULT_PATH


def _parse_road(road_id: str, raw: object) -> RoadRegistration:
    if not isinstance(raw, dict):
        raise ControlRegistryError(f"路口 {road_id} 的登记必须是对象")
    cameras_raw = raw.get("cameras", {})
    if not isinstance(cameras_raw, dict):
        raise ControlRegistryError(f"路口 {road_id} 的 cameras 必须是对象")
    cameras: dict[str, str] = {}
    for key, value in cameras_raw.items():
        direction = str(key).upper()
        if direction not in CAMERA_DIRECTIONS:
            raise ControlRegistryError(
                f"路口 {road_id} 的摄像头方向非法: {key!r}（仅支持 U/D/L/R）"
            )
        text = str(value).strip()
        if not text.isdigit():
            raise ControlRegistryError(
                f"路口 {road_id} 的摄像头编码必须是数字: {value!r}"
            )
        cameras[direction] = text
    profile = raw.get("profile")
    if profile is not None and not isinstance(profile, str):
        raise ControlRegistryError(f"路口 {road_id} 的 profile 必须是字符串")
    return RoadRegistration(
        road_id=road_id,
        enabled=bool(raw.get("enabled", False)),
        cameras=cameras,
        profile=profile,
    )


def load_registry(
    path: str | os.PathLike | None = None,
    *,
    use_cache: bool = True,
) -> dict[str, RoadRegistration]:
    """读取并校验注册表；文件缺失或非法时抛 ``ControlRegistryError``。"""
    target = _registry_path(path)
    try:
        stat = target.stat()
    except OSError as error:
        raise ControlRegistryError(f"注册表不存在: {target}") from error

    version = (stat.st_mtime_ns, stat.st_size)
    if use_cache:
        with _CACHE_LOCK:
            cached = _CACHE.get(str(target))
            if cached is not None and cached[0] == version:
                return dict(cached[1])

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ControlRegistryError(f"注册表不是合法 JSON: {target}") from error

    roads_raw = data.get("roads") if isinstance(data, dict) else None
    if not isinstance(roads_raw, dict):
        raise ControlRegistryError(f"注册表缺少 roads 对象: {target}")

    registry: dict[str, RoadRegistration] = {}
    for road_id, raw in roads_raw.items():
        text_id = str(road_id)
        if not text_id.isdigit():
            raise ControlRegistryError(f"非法路口 ID: {road_id!r}")
        registry[text_id] = _parse_road(text_id, raw)

    if use_cache:
        with _CACHE_LOCK:
            _CACHE[str(target)] = (version, dict(registry))
    return registry


def get_registration(
    road_id: str,
    path: str | os.PathLike | None = None,
) -> RoadRegistration | None:
    """返回路口登记信息；未登记返回 None。"""
    return load_registry(path).get(str(road_id))


def is_enabled(road_id: str, path: str | os.PathLike | None = None) -> bool:
    """路口是否已登记且启用。"""
    registration = get_registration(road_id, path)
    return bool(registration is not None and registration.enabled)


def clear_cache() -> None:
    """清空按文件版本建立的缓存（测试用）。"""
    with _CACHE_LOCK:
        _CACHE.clear()
