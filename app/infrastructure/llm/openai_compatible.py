"""OpenAI-compatible chat completion client.

This adapter keeps AITC independent from local torch/transformers versions.
It can talk to vLLM, SGLang, DashScope-compatible gateways, or any service
that exposes `/v1/chat/completions`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Sequence
from urllib import error, request


@dataclass(frozen=True, slots=True)
class ChatCompletionResult:
    """Normalized chat result returned to the agent layer."""

    content: str
    reasoning_content: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


class OpenAICompatibleLLMClient:
    """Small dependency-free client for OpenAI-compatible model services."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        model: str = "Qwen3-0.6B",
        api_key: str = "EMPTY",
        timeout_seconds: float = 60,
        default_max_tokens: int = 1024,
        enable_thinking: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.default_max_tokens = default_max_tokens
        self.enable_thinking = enable_thinking

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        temperature: float = 0.7,
        top_p: float = 0.8,
        max_tokens: int | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> ChatCompletionResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens or self.default_max_tokens,
        }
        if self.enable_thinking:
            payload["extra_body"] = {"enable_thinking": True}
        if extra_body:
            payload.setdefault("extra_body", {}).update(dict(extra_body))

        response = self._post_json("/chat/completions", payload)
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError("LLM response does not contain choices")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        reasoning_content = message.get("reasoning_content")
        return ChatCompletionResult(
            content=str(content),
            reasoning_content=str(reasoning_content) if reasoning_content is not None else None,
            raw=response,
        )

    def list_models(self) -> Mapping[str, Any]:
        return self._get_json("/models")

    def _post_json(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.base_url + path,
            data=body,
            headers=self._headers(),
            method="POST",
        )
        return self._open_json(req)

    def _get_json(self, path: str) -> Mapping[str, Any]:
        req = request.Request(
            self.base_url + path,
            headers=self._headers(),
            method="GET",
        )
        return self._open_json(req)

    def _open_json(self, req: request.Request) -> Mapping[str, Any]:
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM service returned HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"LLM service is unavailable: {exc.reason}") from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
