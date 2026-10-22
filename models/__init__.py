"""LLM service adapters."""

from .openai_compatible import ChatCompletionResult, OpenAICompatibleLLMClient
from .errors import (
    ModelGatewayError, ModelDisabledError, ModelUnavailableError,
    ModelTimeoutError, ModelResponseError,
)
from .gateway import ModelGateway, as_model_gateway
from .providers import DeepSeekProvider, DisabledProvider, MockProvider, QwenProvider
from .schemas import ModelMessage, ModelRequest, ModelResponse

__all__ = [
    "ChatCompletionResult",
    "OpenAICompatibleLLMClient",
    "ModelGateway", "as_model_gateway", "ModelMessage", "ModelRequest", "ModelResponse",
    "QwenProvider", "DeepSeekProvider", "MockProvider", "DisabledProvider", "ModelGatewayError",
    "ModelDisabledError", "ModelUnavailableError", "ModelTimeoutError", "ModelResponseError",
]
