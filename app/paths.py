"""项目文件路径集中定义（唯一来源，允许环境变量覆盖）。

把散落在各模块的配置文件路径收敛到这里：
- 默认路径基于项目根目录；
- 部署时可通过环境变量覆盖，不用改代码。
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv_for_paths() -> None:
    """路径模块被最早导入，先加载项目根目录 .env，保证 AITC_DATA_ROOT 生效。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        # 这里只提前加载路径根目录，其他配置仍交给 app.config 的 dotenv 处理，
        # 避免测试/默认值被 .env 里的 AITC_TCP_HOST 等覆盖。
        if key == "AITC_DATA_ROOT" and key not in os.environ:
            os.environ[key] = value


_load_dotenv_for_paths()


def _resolve(env_name: str, default: Path) -> Path:
    value = os.getenv(env_name)
    if value is None or not value.strip():
        return default
    return Path(value.strip())


GREEN_WAVE_CORRIDORS_PATH = _resolve(
    "AITC_GREEN_WAVE_CORRIDORS_PATH",
    PROJECT_ROOT / "lib" / "green_wave_corridors.json",
)
# 运行期可变状态根目录：默认仍在版本目录，生产通过 AITC_DATA_ROOT 指向 ../shared
_DATA_ROOT_ENV = os.getenv("AITC_DATA_ROOT", "").strip()
DATA_ROOT = Path(_DATA_ROOT_ENV) if _DATA_ROOT_ENV else PROJECT_ROOT
LOGS_DIR = DATA_ROOT / "logs_data"
# 未配置共享目录时保持旧布局 lib/experience_pool，避免本地/旧部署行为变化
EXPERIENCE_POOL_DIR = (
    DATA_ROOT / "experience_pool"
    if _DATA_ROOT_ENV
    else PROJECT_ROOT / "lib" / "experience_pool"
)
EXPERIENCE_ARTIFACT_DIR = LOGS_DIR / "experience_pool" / "daily"
SHADOW_LOG_DIR = LOGS_DIR / "shadow"

INTERSECTION_RESULT_CONFIG_PATH = _resolve(
    "AITC_INTERSECTION_RESULT_CONFIG_PATH",
    PROJECT_ROOT / "intersection_result_config.json",
)
ROAD_INFO_PATH = _resolve(
    "AITC_ROAD_INFO_PATH",
    PROJECT_ROOT / "lib" / "road_info.json",
)
