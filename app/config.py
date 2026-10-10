"""运行配置基线。

DataHub 与模型配置使用 pydantic-settings，环境读取仍集中在本模块。
其余字段暂时保留既有加载规则，避免改变部署行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

from pydantic import AliasChoices, Field, StrictBool, StrictInt, field_validator, model_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict


T = TypeVar("T")

DEFAULT_MEMORY_WINDOW = 20
DEFAULT_DATAHUB_EVENT_LIMIT = 2048


class ExperienceReleaseSettings(BaseSettings):
    """经验发布与发送日志共用同一个激活清单路径。"""

    model_config = SettingsConfigDict(
        env_prefix="AITC_EXPERIENCE_", extra="ignore", frozen=True,
    )

    versions_dir: Path = Path(__file__).resolve().parents[1] / "lib" / "experience_versions"
    manifest: Path | None = None

    @property
    def active_manifest_path(self) -> Path:
        return (self.manifest or self.versions_dir / "active_manifest.json").resolve()


class TrafficMemorySettings(BaseSettings):
    """最近决策轮数与每路口原始事件容量；非法值在装配时失败。"""

    model_config = SettingsConfigDict(env_prefix="AITC_", extra="ignore", populate_by_name=True)

    memory_window: int = Field(
        default=DEFAULT_MEMORY_WINDOW, gt=0,
        validation_alias=AliasChoices("AITC_MEMORY_WINDOW", "MEMORY_WINDOW"),
    )
    datahub_event_limit: int = Field(default=DEFAULT_DATAHUB_EVENT_LIMIT, gt=0)

    @field_validator("memory_window", "datahub_event_limit", mode="before")
    @classmethod
    def integer_capacity(cls, value: Any) -> Any:
        if isinstance(value, (bool, float)):
            raise ValueError("capacity must be a positive integer")
        if isinstance(value, str):
            return int(value)
        return value


class _ModelEnvironmentSource(EnvSettingsSource):
    """沿用旧配置的空白跳过规则；只在环境边界解析标量。"""

    def _load_env_vars(self) -> dict[str, str]:
        return {
            key: value.strip()
            for key, value in super()._load_env_vars().items()
            if isinstance(value, str) and value.strip()
        }

    def prepare_field_value(self, field_name: str, field: Any, value: Any, value_is_complex: bool) -> Any:
        if isinstance(value, str):
            if field.annotation is bool:
                normalized = value.lower()
                if normalized in {"1", "true", "yes", "on"}:
                    return True
                if normalized in {"0", "false", "no", "off"}:
                    return False
            elif field.annotation in {int, float}:
                try:
                    return field.annotation(value)
                except ValueError:
                    pass  # 保留原值，让严格字段校验给出字段级错误。
        return value


class ModelSettings(BaseSettings):
    """模型网关的唯一配置与默认值来源；构造时验证实际使用的 provider。"""

    model_config = SettingsConfigDict(
        env_prefix="AITC_", extra="ignore", populate_by_name=True,
        strict=True, frozen=True, allow_inf_nan=False, hide_input_in_errors=True,
    )

    enabled: bool = Field(
        default=True, validation_alias=AliasChoices("AITC_LLM_ENABLED", "LLM_ENABLED"),
    )
    provider: Literal["qwen", "deepseek", "mock", "disabled"] = Field(
        default="qwen", validation_alias=AliasChoices("AITC_MODEL_PROVIDER", "MODEL_PROVIDER"),
    )
    name: str = Field(
        default="Qwen3-0.6B",
        validation_alias=AliasChoices("AITC_MODEL_NAME", "AITC_LLM_MODEL", "MODEL_NAME", "LLM_MODEL_ID"),
    )
    base_url: str = Field(
        default="http://127.0.0.1:8000/v1",
        validation_alias=AliasChoices("AITC_MODEL_BASE_URL", "AITC_LLM_BASE_URL", "MODEL_BASE_URL", "LLM_BASE_URL"),
    )
    api_key: str = Field(
        default="EMPTY", repr=False,
        validation_alias=AliasChoices("AITC_MODEL_API_KEY", "AITC_LLM_API_KEY", "MODEL_API_KEY", "LLM_API_KEY"),
    )
    timeout_seconds: float = Field(
        default=60,
        validation_alias=AliasChoices("AITC_LLM_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS"),
    )
    max_tokens: int = Field(
        default=1024, validation_alias=AliasChoices("AITC_LLM_MAX_TOKENS", "LLM_MAX_TOKENS"),
    )
    enable_thinking: bool = Field(
        default=False, validation_alias=AliasChoices("AITC_LLM_ENABLE_THINKING", "LLM_ENABLE_THINKING"),
    )
    required: bool = Field(
        default=False, validation_alias=AliasChoices("AITC_LLM_REQUIRED", "LLM_REQUIRED"),
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls: type[BaseSettings], init_settings: Any, env_settings: Any,
        dotenv_settings: Any, file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        # .env 仍由本模块的 _load_dotenv 处理，不引入第二套加载优先级。
        return init_settings, _ModelEnvironmentSource(settings_cls)

    @property
    def effective_provider(self) -> Literal["qwen", "deepseek", "mock", "disabled"]:
        return self.provider if self.enabled else "disabled"

    @model_validator(mode="after")
    def validate_active_provider(self) -> "ModelSettings":
        if self.effective_provider in {"qwen", "deepseek"}:
            if not self.base_url.strip():
                raise ValueError("llm_base_url / base_url must not be empty")
            if not self.name.strip():
                raise ValueError("llm_model / name must not be empty")
            if self.timeout_seconds <= 0:
                raise ValueError("llm_timeout_seconds / timeout_seconds must be positive")
            if self.max_tokens <= 0:
                raise ValueError("llm_max_tokens / max_tokens must be positive")
            if self.effective_provider == "deepseek":
                if not self.api_key.strip() or self.api_key == "EMPTY":
                    raise ValueError("DeepSeek requires an API key")
                if self.name == type(self).model_fields["name"].default:
                    raise ValueError("DeepSeek requires an explicit model name")
                if self.base_url == type(self).model_fields["base_url"].default:
                    raise ValueError("DeepSeek requires an explicit API base URL")
        return self


class ControlAgentSettings(BaseSettings):
    """周期模型增强显式启用；预算独立于既有 HTTP Agent。"""

    model_config = SettingsConfigDict(
        env_prefix="AITC_CONTROL_AGENT_", extra="ignore", frozen=True,
        strict=True, allow_inf_nan=False,
    )

    enabled: StrictBool = False
    max_model_calls: StrictInt = Field(default=3, ge=1, le=6)
    timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    max_context_chars: StrictInt = Field(default=16000, ge=2000, le=100000)
    failure_cooldown_seconds: float = Field(default=30.0, gt=0, le=3600)

    @classmethod
    def settings_customise_sources(
        cls, settings_cls: type[BaseSettings], init_settings: Any, env_settings: Any,
        dotenv_settings: Any, file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        return init_settings, _ModelEnvironmentSource(settings_cls)

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
    llm_enabled: bool = ModelSettings.model_fields["enabled"].default
    model_provider: str = ModelSettings.model_fields["provider"].default
    llm_base_url: str = ModelSettings.model_fields["base_url"].default
    llm_model: str = ModelSettings.model_fields["name"].default
    llm_api_key: str = field(default=ModelSettings.model_fields["api_key"].default, repr=False)
    llm_timeout_seconds: float = ModelSettings.model_fields["timeout_seconds"].default
    llm_max_tokens: int = ModelSettings.model_fields["max_tokens"].default
    llm_enable_thinking: bool = ModelSettings.model_fields["enable_thinking"].default
    llm_required: bool = ModelSettings.model_fields["required"].default

    # ── 控制快照 ──
    control_snapshot_enabled: bool = False   # 是否落盘每轮决策输入快照

    # ── DataHub ──
    traffic_memory: TrafficMemorySettings = field(default_factory=TrafficMemorySettings)

    # ── 经验版本追溯 ──
    experience_release: ExperienceReleaseSettings = field(default_factory=ExperienceReleaseSettings)

    # ── 受约束的周期认知层 ──
    control_agent: ControlAgentSettings = field(default_factory=ControlAgentSettings, kw_only=True)

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        """从环境变量加载配置，未设置时沿用字段默认值。

        先加载项目根目录 ``.env``（不覆盖已存在的环境变量）；
        同一配置存在两套变量名时，``AITC_*`` 优先于 ``LLM_*``。
        """
        _load_dotenv()
        model = ModelSettings()
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
            llm_enabled=model.enabled,
            model_provider=model.provider,
            llm_base_url=model.base_url,
            llm_model=model.name,
            llm_api_key=model.api_key,
            llm_timeout_seconds=model.timeout_seconds,
            llm_max_tokens=model.max_tokens,
            llm_enable_thinking=model.enable_thinking,
            llm_required=model.required,
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
        self.model_settings
        return self

    @property
    def model_settings(self) -> ModelSettings:
        """从已装配字段建立模型配置，环境变化不会改写显式 RuntimeSettings。"""
        return ModelSettings.model_validate({
            "enabled": self.llm_enabled,
            "provider": self.model_provider,
            "name": self.llm_model,
            "base_url": self.llm_base_url,
            "api_key": self.llm_api_key,
            "timeout_seconds": self.llm_timeout_seconds,
            "max_tokens": self.llm_max_tokens,
            "enable_thinking": self.llm_enable_thinking,
            "required": self.llm_required,
        })
    run_mode: RunMode = RunMode.DEVELOPMENT
