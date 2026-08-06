"""LLM service adapters."""

from .openai_compatible import ChatCompletionResult, OpenAICompatibleLLMClient

__all__ = [
    "ChatCompletionResult",
    "OpenAICompatibleLLMClient",
]
