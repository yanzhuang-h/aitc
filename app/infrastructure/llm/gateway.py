"""统一模型调用入口，兼容现有同步 HTTP Agent 和异步调用者。"""

import asyncio
from typing import Protocol

from pydantic import ValidationError

from .errors import ModelResponseError
from .providers import QwenProvider
from .schemas import ModelRequest, ModelResponse


class ModelProvider(Protocol):
    name: str
    enabled: bool
    model: str | None
    base_url: str

    def invoke(self, request: ModelRequest) -> ModelResponse: ...
    def check_ready(self) -> dict: ...


class ModelGateway:
    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    @property
    def enabled(self) -> bool:
        return self.provider.enabled

    @property
    def provider_name(self) -> str:
        return self.provider.name

    @property
    def model(self) -> str | None:
        return self.provider.model

    @property
    def base_url(self) -> str:
        return self.provider.base_url

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        # 复用既有 urllib 传输的 socket timeout；不伪装可中止工作线程的总 deadline。
        validated = ModelRequest.model_validate(request).model_copy(deep=True)
        return await asyncio.to_thread(self._invoke, validated)

    def invoke_sync(self, request: ModelRequest) -> ModelResponse:
        # 不运行嵌套事件循环；原同步协议入口直接经过同一边界和 provider。
        validated = ModelRequest.model_validate(request).model_copy(deep=True)
        return self._invoke(validated)

    def _invoke(self, validated: ModelRequest) -> ModelResponse:
        try:
            result = self.provider.invoke(validated)
            return ModelResponse.model_validate(result).model_copy(deep=True)
        except ValidationError as error:
            raise ModelResponseError(f"Invalid model response: {error}") from error

    def check_ready(self) -> dict:
        return self.provider.check_ready()

    def list_models(self) -> dict:
        """兼容旧应用健康检查接口，实际仍经过统一网关。"""
        return self.check_ready()


def as_model_gateway(client) -> ModelGateway:
    """旧注入 client 仅在入口包装一次；新生产装配传入共享 gateway。"""
    return client if isinstance(client, ModelGateway) else ModelGateway(QwenProvider(client))
