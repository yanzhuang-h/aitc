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
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# 中文类型名 → 英文报错文案（报错文案先中文后英文）
_TYPE_NAME_EN = {"字符串": "a string", "整数": "an integer", "数字": "a number"}


def _strip_inline_comment(value: str) -> str:
    """剥离配置值中的行内注释与引号。

    支持 ``KEY="value" # 注释`` 与 ``KEY=value # 注释`` 两种形式；
    引号内的 ``#`` 不会被当作注释。行内注释要求 ``#`` 前有空格，
    不处理 ``KEY=value#注释``（无空格）形式。
    """
    value = value.strip()
    if value[:1] in {'"', "'"}:
        quote = value[0]
        end = value.find(quote, 1)
        if end == -1:
            return value[1:]
        return value[1:end]
    hash_pos = value.find(" #")
    if hash_pos != -1:
        return value[:hash_pos].strip()
    return value


def _load_dotenv(path: str | os.PathLike | None = None) -> None:
    """零依赖加载项目根目录的 .env 文件到环境变量。

    遵循 dotenv 惯例：已存在的环境变量不会被覆盖。支持 ``#`` 注释、
    ``KEY=VALUE`` 形式、带引号的值以及行内注释（``KEY=VALUE # 注释``）。
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
        value = _strip_inline_comment(value)
        if key and key not in os.environ:
            os.environ[key] = value


def _read_value(
    name: str,
    default: T,
    cast: Callable[[str], T],
    type_name: str,
    *aliases: str,
) -> T:
    """按优先级读取第一个存在的环境变量，并转换为目标类型。

    优先级：``name`` > ``aliases``（按顺序）> ``default``；
    转换失败抛 ValueError，服务启动即失败（fail-fast）。
    """
    for candidate in (name, *aliases):
        value = os.getenv(candidate)
        if value is None or not value.strip():
            continue
        try:
            return cast(value.strip())
        except ValueError as error:
            type_name_en = _TYPE_NAME_EN.get(type_name, type_name)
            raise ValueError(f"{candidate} 必须是{type_name}（must be {type_name_en}）") from error
    return default


def _read_path(name: str, default: str | Path) -> Path:
    """读取路径型环境变量：未设置用默认值，显式设为空白则报错。"""
    value = os.getenv(name)
    if value is None:
        return Path(default)
    if not value.strip():
        raise ValueError(f"{name} 不能为空（must not be empty）")
    return Path(value.strip())


def _read_bool(name: str, default: bool, *aliases: str) -> bool:
    """读取布尔型环境变量：接受 1/true/yes/on 与 0/false/no/off。"""
    for candidate in (name, *aliases):
        value = os.getenv(candidate)
        if value is None or not value.strip():
            continue
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{candidate} 必须是布尔值（must be a boolean）")
    return default


class RunMode(StrEnum):
    """AITC 的运行模式。"""

    REPLAY = "replay"
    DEVELOPMENT = "development"
    PRODUCTION = "production"


@dataclass(frozen=True)
class RuntimeSettings:
    """运行服务、数据目录与调度任务的集中配置（字段默认值即唯一默认来源）。

    刻意不启用 slots：from_environment 通过 ``cls.<字段>`` 引用字段默认值，
    无 slots 时类属性就是默认值；配置是进程内单实例，省内存无意义。
    """

    # ── 网络 ──
    tcp_host: str = "127.0.0.1"          # TCP 监听地址（数据上报与结果广播）
    tcp_port: int = 65432                # TCP 监听端口
    tcp_buffer_size: int = 1024 * 1024   # 单次 socket 读取字节数（1MB）
    http_host: str = "127.0.0.1"         # HTTP 监听地址（雷达/配置/Agent/健康检查）
    http_port: int = 8088                # HTTP 监听端口

    # ── 周期 ──
    decision_interval_seconds: float = 50        # 决策周期：每 50s 聚合窗口产出方案
    result_send_interval_seconds: float = 50     # 广播周期：每 50s 向客户端发送最新结果
    flow_duration_seconds: int = 150             # 短窗聚合窗口：决策时取最近 150s 流量

    # ── 调度 ──
    prediction_hour: int = 3              # 每日预测执行时刻（时）
    prediction_minute: int = 0            # 每日预测执行时刻（分）
    enable_config_sync: bool = False      # Nacos 配置同步开关（当前默认关闭）
    enable_prediction_scheduler: bool = True   # 每日流量/排队预测调度开关
    enable_experience_pool_scheduler: bool = True  # 经验池调度开关

    # ── 落盘路径 ──
    runtime_data_dir: Path = Path("infra/data/runtime")      # 长期历史仓库（jsonl）
    runtime_output_dir: Path = Path("logs_data")             # 兼容日志输出目录
    prediction_data_dir: Path = Path("logs_data")            # 预测历史与每日预测输出目录
    control_snapshot_dir: Path = Path("logs_data/control_snapshots")  # 控制快照目录

    # ── LLM（OpenAI 兼容接入） ──
    llm_base_url: str = "http://127.0.0.1:8000/v1"   # 模型服务地址（vLLM/SGLang/DeepSeek）
    llm_model: str = "Qwen3-0.6B"                    # 模型名称
    llm_api_key: str = "EMPTY"                       # API 密钥
    llm_timeout_seconds: float = 60                  # 单次请求超时（秒）
    llm_max_tokens: int = 1024                       # 单次生成最大 token 数
    llm_enable_thinking: bool = False                # 是否开启思考模式
    llm_required: bool = False                       # LLM 不可达时是否禁止启动

    # ── 控制快照 ──
    control_snapshot_enabled: bool = False   # 是否落盘每轮决策输入快照

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        """从环境变量加载配置，未设置时沿用字段默认值。

        先加载项目根目录 ``.env``（不覆盖已存在的环境变量）；
        同一配置存在两套变量名时，``AITC_*`` 优先于 ``LLM_*``。
        """
        _load_dotenv()
        run_mode = RunMode(os.getenv("AITC_RUN_MODE", RunMode.DEVELOPMENT))
        # 运行模式只决定以下默认值；显式环境变量仍可覆盖
        mode_defaults = {
            RunMode.REPLAY: {
                "tcp_host": cls.tcp_host,
                "http_host": cls.http_host,
                "enable_config_sync": cls.enable_config_sync,
                "enable_prediction_scheduler": False,
            },
            RunMode.DEVELOPMENT: {
                "tcp_host": cls.tcp_host,
                "http_host": cls.http_host,
                "enable_config_sync": cls.enable_config_sync,
                "enable_prediction_scheduler": cls.enable_prediction_scheduler,
            },
            RunMode.PRODUCTION: {
                "tcp_host": "0.0.0.0",          # 生产绑定所有网卡，对外可达
                "http_host": "0.0.0.0",
                "enable_config_sync": cls.enable_config_sync,
                "enable_prediction_scheduler": cls.enable_prediction_scheduler,
            },
        }[run_mode]
        return cls(
            run_mode=run_mode,
            tcp_host=_read_value("AITC_TCP_HOST", mode_defaults["tcp_host"], str, "字符串"),
            tcp_port=_read_value("AITC_TCP_PORT", cls.tcp_port, int, "整数"),
            tcp_buffer_size=_read_value("AITC_TCP_BUFFER_SIZE", cls.tcp_buffer_size, int, "整数"),
            http_host=_read_value("AITC_HTTP_HOST", mode_defaults["http_host"], str, "字符串"),
            http_port=_read_value("AITC_HTTP_PORT", cls.http_port, int, "整数"),
            decision_interval_seconds=_read_value("AITC_DECISION_INTERVAL_SECONDS", cls.decision_interval_seconds, float, "数字"),
            result_send_interval_seconds=_read_value("AITC_RESULT_SEND_INTERVAL_SECONDS", cls.result_send_interval_seconds, float, "数字"),
            flow_duration_seconds=_read_value("AITC_FLOW_DURATION_SECONDS", cls.flow_duration_seconds, int, "整数"),
            prediction_hour=_read_value("AITC_PREDICTION_HOUR", cls.prediction_hour, int, "整数"),
            prediction_minute=_read_value("AITC_PREDICTION_MINUTE", cls.prediction_minute, int, "整数"),
            runtime_data_dir=_read_path("AITC_RUNTIME_DATA_DIR", cls.runtime_data_dir),
            runtime_output_dir=_read_path("AITC_RUNTIME_OUTPUT_DIR", cls.runtime_output_dir),
            prediction_data_dir=_read_path("AITC_PREDICTION_DATA_DIR", cls.prediction_data_dir),
            enable_config_sync=_read_bool("AITC_ENABLE_CONFIG_SYNC", mode_defaults["enable_config_sync"]),
            enable_prediction_scheduler=_read_bool("AITC_ENABLE_PREDICTION_SCHEDULER", mode_defaults["enable_prediction_scheduler"]),
            enable_experience_pool_scheduler=_read_bool("AITC_EXPERIENCE_POOL_ENABLED", cls.enable_experience_pool_scheduler),
            llm_base_url=_read_value("AITC_LLM_BASE_URL", cls.llm_base_url, str, "字符串", "LLM_BASE_URL"),
            llm_model=_read_value("AITC_LLM_MODEL", cls.llm_model, str, "字符串", "LLM_MODEL_ID"),
            llm_api_key=_read_value("AITC_LLM_API_KEY", cls.llm_api_key, str, "字符串", "LLM_API_KEY"),
            llm_timeout_seconds=_read_value("AITC_LLM_TIMEOUT_SECONDS", cls.llm_timeout_seconds, float, "数字", "LLM_TIMEOUT_SECONDS"),
            llm_max_tokens=_read_value("AITC_LLM_MAX_TOKENS", cls.llm_max_tokens, int, "整数", "LLM_MAX_TOKENS"),
            llm_enable_thinking=_read_bool("AITC_LLM_ENABLE_THINKING", cls.llm_enable_thinking, "LLM_ENABLE_THINKING"),
            llm_required=_read_bool("AITC_LLM_REQUIRED", cls.llm_required, "LLM_REQUIRED"),
            control_snapshot_enabled=_read_bool("AITC_CONTROL_SNAPSHOT_ENABLED", cls.control_snapshot_enabled),
            control_snapshot_dir=_read_path("AITC_CONTROL_SNAPSHOT_DIR", cls.control_snapshot_dir),
        )

    def validate(self) -> "RuntimeSettings":
        """在创建网络服务前校验关键配置范围；不合法直接抛 ValueError。"""
        for name, port in (("tcp_port", self.tcp_port), ("http_port", self.http_port)):
            if not 1 <= port <= 65535:
                raise ValueError(f"{name} 端口必须在 1-65535 之间（must be between 1 and 65535）")
        if self.tcp_buffer_size <= 0:
            raise ValueError("tcp_buffer_size 必须为正数（must be positive）")
        if self.decision_interval_seconds <= 0 or self.result_send_interval_seconds <= 0:
            raise ValueError("运行时周期必须为正数（runtime intervals must be positive）")
        if self.flow_duration_seconds <= 0:
            raise ValueError("flow_duration_seconds 必须为正数（must be positive）")
        if not 0 <= self.prediction_hour <= 23 or not 0 <= self.prediction_minute <= 59:
            raise ValueError("预测调度时刻超出范围（prediction schedule is out of range）")
        if not self.llm_base_url.strip():
            raise ValueError("llm_base_url 不能为空（must not be empty）")
        if not self.llm_model.strip():
            raise ValueError("llm_model 不能为空（must not be empty）")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("llm_timeout_seconds 必须为正数（must be positive）")
        if self.llm_max_tokens <= 0:
            raise ValueError("llm_max_tokens 必须为正数（must be positive）")
        return self
    run_mode: RunMode = RunMode.DEVELOPMENT
