"""模型调用的严格边界；工具动作的业务契约留给 Agent 层。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.models.contract_types import CONTRACT_CONFIG, FiniteNumber, NonEmptyString


class ModelMessage(BaseModel):
    model_config = CONTRACT_CONFIG

    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ModelRequest(BaseModel):
    model_config = CONTRACT_CONFIG

    messages: list[ModelMessage] = Field(min_length=1)
    temperature: FiniteNumber = Field(default=0.7, ge=0, le=2)
    top_p: FiniteNumber = Field(default=0.8, ge=0, le=1)
    max_tokens: StrictInt | None = Field(default=None, gt=0)
    extra_body: dict[str, Any] | None = None
    max_retries: StrictInt | None = Field(default=None, ge=0)


class ModelResponse(BaseModel):
    model_config = CONTRACT_CONFIG

    content: str
    reasoning_content: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class _CompletionMessage(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    # OpenAI 兼容服务在仅返回 tool_calls 时允许 content=null。
    content: str | None = None
    reasoning_content: str | None = None


class _CompletionChoice(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    message: _CompletionMessage


class ChatCompletionEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    choices: list[_CompletionChoice] = Field(min_length=1)


class _ModelDescriptor(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    id: NonEmptyString


class ModelListEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    data: list[_ModelDescriptor]
