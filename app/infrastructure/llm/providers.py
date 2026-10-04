"""三个实际模型实现；只有 Qwen provider 可调用模型传输层。"""

from collections import deque
import json
from threading import Lock
from typing import Sequence
from urllib.error import URLError

from pydantic import ValidationError

from .errors import (
    ModelDisabledError, ModelGatewayError, ModelResponseError,
    ModelTimeoutError, ModelUnavailableError,
)
from .openai_compatible import LLMServiceError
from .schemas import ModelListEnvelope, ModelRequest, ModelResponse


class QwenProvider:
    name = "qwen"
    enabled = True

    def __init__(self, client) -> None:
        self.client = client

    @property
    def model(self) -> str | None:
        return getattr(self.client, "model", None)

    @property
    def base_url(self) -> str:
        return getattr(self.client, "base_url", "")

    def invoke(self, request: ModelRequest) -> ModelResponse:
        result = self._call(
            self.client.chat,
            [message.model_dump() for message in request.messages],
            temperature=request.temperature, top_p=request.top_p,
            max_tokens=request.max_tokens,
            **({"extra_body": request.extra_body} if request.extra_body is not None else {}),
            **({"max_retries": request.max_retries} if request.max_retries is not None else {}),
        )
        return ModelResponse(
            content=result.content,
            reasoning_content=getattr(result, "reasoning_content", None),
            raw=getattr(result, "raw", {}),
        )

    def check_ready(self) -> dict:
        response = self._call(self.client.list_models)
        try:
            ModelListEnvelope.model_validate(response)
        except ValidationError as error:
            raise ModelResponseError(f"Invalid model list response: {error}") from error
        return response

    @staticmethod
    def _call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except LLMServiceError as error:
            cause = error.__cause__
            timed_out = (
                error.status_code in (408, 504)
                or isinstance(cause, TimeoutError)
                or isinstance(cause, URLError) and isinstance(cause.reason, TimeoutError)
            )
            exception = ModelTimeoutError if timed_out else ModelUnavailableError
            raise exception(str(error), status_code=error.status_code) from error
        except TimeoutError as error:
            raise ModelTimeoutError(str(error)) from error
        except (OSError, URLError) as error:
            raise ModelUnavailableError(str(error)) from error
        except (ValidationError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ModelResponseError(f"Invalid model response: {error}") from error


class MockProvider:
    """默认空文本或显式响应脚本；不产生虚构交通观测或配时方案。"""

    name = "mock"
    enabled = True
    base_url = ""

    def __init__(
        self, responses: Sequence[ModelResponse] | None = None, *, model: str = "mock",
    ) -> None:
        self.model = model
        self._responses = None if responses is None else deque(
            ModelResponse.model_validate(item).model_copy(deep=True) for item in responses
        )
        self._lock = Lock()

    def invoke(self, request: ModelRequest) -> ModelResponse:
        if self._responses is None:
            return ModelResponse(content="")
        with self._lock:
            if not self._responses:
                raise ModelGatewayError("Mock response script is exhausted")
            return self._responses.popleft().model_copy(deep=True)

    def check_ready(self) -> dict:
        return {"data": [{"id": self.model}]}


class DisabledProvider:
    name = "disabled"
    enabled = False
    model = None
    base_url = ""

    def invoke(self, request: ModelRequest) -> ModelResponse:
        raise ModelDisabledError("Model calls are disabled")

    def check_ready(self) -> dict:
        return {}
