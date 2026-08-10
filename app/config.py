"""运行配置基线。

当前不引入新的第三方配置依赖。默认值与既有运行行为保持一致，部署时可
通过环境变量覆盖。后续引入 ``pydantic-settings`` 时仅替换本模块的加载
实现，不改变运行装配层的依赖方式。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path


def _load_dotenv(path: str | os.PathLike | None = None) -> None:
    """零依赖加载项目根目录的 .env 文件到环境变量。

    遵循 dotenv 惯例：已存在的环境变量不会被覆盖。支持 ``#`` 注释、
    ``KEY=VALUE`` 形式以及带引号的值。
    """
    env_path = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _read_str(name: str, default: str, *aliases: str) -> str:
    """按优先级读取第一个存在的字符串环境变量。"""
    for candidate in (name, *aliases):
        value = os.getenv(candidate)
        if value is not None and value.strip():
            return value.strip()
    return default


def _read_int(name: str, default: int, *aliases: str) -> int:
    for candidate in (name, *aliases):
        value = os.getenv(candidate)
        if value is None or not value.strip():
            continue
        try:
            return int(value)
        except ValueError as error:
            raise ValueError(f"{candidate} must be an integer") from error
    return default


def _read_float(name: str, default: float, *aliases: str) -> float:
    for candidate in (name, *aliases):
        value = os.getenv(candidate)
        if value is None or not value.strip():
            continue
        try:
            return float(value)
        except ValueError as error:
            raise ValueError(f"{candidate} must be a number") from error
    return default


def _read_path(name: str, default: str) -> Path:
    value = os.getenv(name, default).strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return Path(value)


def _read_bool(name: str, default: bool, *aliases: str) -> bool:
    for candidate in (name, *aliases):
        value = os.getenv(candidate)
        if value is None or not value.strip():
            continue
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{candidate} must be a boolean")
    return default


class RunMode(StrEnum):
    """AITC 的运行模式。"""

    REPLAY = "replay"
    DEVELOPMENT = "development"
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """运行服务、数据目录与调度任务的集中配置。"""

    tcp_host: str = "127.0.0.1"
    tcp_port: int = 65432
    tcp_buffer_size: int = 1024 * 1024
    http_host: str = "127.0.0.1"
    http_port: int = 8088
    decision_interval_seconds: float = 50
    result_send_interval_seconds: float = 50
    flow_duration_seconds: int = 150
    prediction_hour: int = 3
    prediction_minute: int = 0
    runtime_data_dir: Path = Path("infra/data/runtime")
    runtime_output_dir: Path = Path("logs_data")
    prediction_data_dir: Path = Path("logs_data")
    enable_config_sync: bool = True
    enable_prediction_scheduler: bool = True
    llm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_model: str = "Qwen3-0.6B"
    llm_api_key: str = "EMPTY"
    llm_timeout_seconds: float = 60
    llm_max_tokens: int = 1024
    llm_enable_thinking: bool = False

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        """从环境变量加载配置，未设置时保持旧代码默认值。

        优先加载项目根目录的 ``.env`` 文件（不覆盖已存在的环境变量），
        因此既可用 ``AITC_*`` 前缀变量，也可直接用通用 ``LLM_*`` 变量。
        """
        _load_dotenv()
        run_mode = RunMode(os.getenv("AITC_RUN_MODE", RunMode.DEVELOPMENT))
        mode_defaults = {
            RunMode.REPLAY: {
                "tcp_host": "127.0.0.1",
                "http_host": "127.0.0.1",
                "enable_config_sync": False,
                "enable_prediction_scheduler": False,
            },
            RunMode.DEVELOPMENT: {
                "tcp_host": "127.0.0.1",
                "http_host": "127.0.0.1",
                "enable_config_sync": True,
                "enable_prediction_scheduler": True,
            },
            RunMode.PRODUCTION: {
                "tcp_host": "0.0.0.0",
                "http_host": "0.0.0.0",
                "enable_config_sync": True,
                "enable_prediction_scheduler": True,
            },
        }[run_mode]
        return cls(
            run_mode=run_mode,
            tcp_host=os.getenv("AITC_TCP_HOST", mode_defaults["tcp_host"]),
            tcp_port=_read_int("AITC_TCP_PORT", 65432),
            tcp_buffer_size=_read_int("AITC_TCP_BUFFER_SIZE", 1024 * 1024),
            http_host=os.getenv("AITC_HTTP_HOST", mode_defaults["http_host"]),
            http_port=_read_int("AITC_HTTP_PORT", 8088),
            decision_interval_seconds=_read_float("AITC_DECISION_INTERVAL_SECONDS", 50),
            result_send_interval_seconds=_read_float("AITC_RESULT_SEND_INTERVAL_SECONDS", 50),
            flow_duration_seconds=_read_int("AITC_FLOW_DURATION_SECONDS", 150),
            prediction_hour=_read_int("AITC_PREDICTION_HOUR", 3),
            prediction_minute=_read_int("AITC_PREDICTION_MINUTE", 0),
            runtime_data_dir=_read_path("AITC_RUNTIME_DATA_DIR", "infra/data/runtime"),
            runtime_output_dir=_read_path("AITC_RUNTIME_OUTPUT_DIR", "logs_data"),
            prediction_data_dir=_read_path("AITC_PREDICTION_DATA_DIR", "logs_data"),
            enable_config_sync=_read_bool("AITC_ENABLE_CONFIG_SYNC", mode_defaults["enable_config_sync"]),
            enable_prediction_scheduler=_read_bool("AITC_ENABLE_PREDICTION_SCHEDULER", mode_defaults["enable_prediction_scheduler"]),
            llm_base_url=_read_str("AITC_LLM_BASE_URL", "http://127.0.0.1:8000/v1", "LLM_BASE_URL"),
            llm_model=_read_str("AITC_LLM_MODEL", "Qwen3-0.6B", "LLM_MODEL_ID"),
            llm_api_key=_read_str("AITC_LLM_API_KEY", "EMPTY", "LLM_API_KEY"),
            llm_timeout_seconds=_read_float("AITC_LLM_TIMEOUT_SECONDS", 60, "LLM_TIMEOUT_SECONDS"),
            llm_max_tokens=_read_int("AITC_LLM_MAX_TOKENS", 1024, "LLM_MAX_TOKENS"),
            llm_enable_thinking=_read_bool("AITC_LLM_ENABLE_THINKING", False, "LLM_ENABLE_THINKING"),
        )

    def validate(self) -> "RuntimeSettings":
        """在创建网络服务前校验关键配置范围。"""
        for name, port in (("tcp_port", self.tcp_port), ("http_port", self.http_port)):
            if not 1 <= port <= 65535:
                raise ValueError(f"{name} must be between 1 and 65535")
        if self.tcp_buffer_size <= 0:
            raise ValueError("tcp_buffer_size must be positive")
        if self.decision_interval_seconds <= 0 or self.result_send_interval_seconds <= 0:
            raise ValueError("runtime intervals must be positive")
        if self.flow_duration_seconds <= 0:
            raise ValueError("flow_duration_seconds must be positive")
        if not 0 <= self.prediction_hour <= 23 or not 0 <= self.prediction_minute <= 59:
            raise ValueError("prediction schedule is out of range")
        if not self.llm_base_url.strip():
            raise ValueError("llm_base_url must not be empty")
        if not self.llm_model.strip():
            raise ValueError("llm_model must not be empty")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("llm_timeout_seconds must be positive")
        if self.llm_max_tokens <= 0:
            raise ValueError("llm_max_tokens must be positive")
        return self
    run_mode: RunMode = RunMode.DEVELOPMENT
