"""项目文件路径集中定义（唯一来源，允许环境变量覆盖）。

把散落在各模块的配置文件路径收敛到这里：
- 默认路径基于项目根目录；
- 部署时可通过环境变量覆盖，不用改代码。
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve(env_name: str, default: Path) -> Path:
    value = os.getenv(env_name)
    if value is None or not value.strip():
        return default
    return Path(value.strip())


GREEN_WAVE_CORRIDORS_PATH = _resolve(
    "AITC_GREEN_WAVE_CORRIDORS_PATH",
    PROJECT_ROOT / "lib" / "green_wave_corridors.json",
)
INTERSECTION_RESULT_CONFIG_PATH = _resolve(
    "AITC_INTERSECTION_RESULT_CONFIG_PATH",
    PROJECT_ROOT / "intersection_result_config.json",
)
ROAD_INFO_PATH = _resolve(
    "AITC_ROAD_INFO_PATH",
    PROJECT_ROOT / "lib" / "road_info.json",
)
