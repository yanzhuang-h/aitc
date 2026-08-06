"""运行配置基线。

当前不引入新的第三方配置依赖。默认值与既有运行行为保持一致，部署时可
通过环境变量覆盖。后续引入 ``pydantic-settings`` 时仅替换本模块的加载
实现，不改变运行装配层的依赖方式。
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error


def _read_path(name: str, default: str) -> Path:
    value = os.getenv(name, default).strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return Path(value)


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

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        """从环境变量加载配置，未设置时保持旧代码默认值。"""
        return cls(
            tcp_host=os.getenv("AITC_TCP_HOST", "127.0.0.1"),
            tcp_port=_read_int("AITC_TCP_PORT", 65432),
            tcp_buffer_size=_read_int("AITC_TCP_BUFFER_SIZE", 1024 * 1024),
            http_host=os.getenv("AITC_HTTP_HOST", "127.0.0.1"),
            http_port=_read_int("AITC_HTTP_PORT", 8088),
            decision_interval_seconds=_read_float("AITC_DECISION_INTERVAL_SECONDS", 50),
            result_send_interval_seconds=_read_float("AITC_RESULT_SEND_INTERVAL_SECONDS", 50),
            flow_duration_seconds=_read_int("AITC_FLOW_DURATION_SECONDS", 150),
            prediction_hour=_read_int("AITC_PREDICTION_HOUR", 3),
            prediction_minute=_read_int("AITC_PREDICTION_MINUTE", 0),
            runtime_data_dir=_read_path("AITC_RUNTIME_DATA_DIR", "infra/data/runtime"),
            runtime_output_dir=_read_path("AITC_RUNTIME_OUTPUT_DIR", "logs_data"),
            prediction_data_dir=_read_path("AITC_PREDICTION_DATA_DIR", "logs_data"),
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
        return self
