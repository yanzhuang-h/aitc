import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.infrastructure.llm import OpenAICompatibleLLMClient
from app.infrastructure.llm.openai_compatible import LLMServiceError


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class _ErrorBody:
    def read(self):
        return b'{"error": "boom"}'


def _http_error(code):
    return HTTPError("http://localhost:8000", code, "error", {}, _ErrorBody())


class OpenAICompatibleLLMClientTest(unittest.TestCase):
    def test_chat_completion_request_and_response_are_normalized(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(req.header_items())
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return _Response({
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                            "reasoning_content": "thinking",
                        }
                    }
                ]
            })

        client = OpenAICompatibleLLMClient(
            base_url="http://localhost:8000/v1/",
            model="Qwen3-0.6B",
            api_key="EMPTY",
            timeout_seconds=12,
            enable_thinking=True,
        )

        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", fake_urlopen):
            result = client.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(captured["url"], "http://localhost:8000/v1/chat/completions")
        self.assertEqual(captured["timeout"], 12)
        self.assertEqual(captured["payload"]["model"], "Qwen3-0.6B")
        self.assertEqual(captured["payload"]["extra_body"]["enable_thinking"], True)
        self.assertEqual(
            captured["payload"]["chat_template_kwargs"]["enable_thinking"], True
        )
        self.assertEqual(result.content, "ok")
        self.assertEqual(result.reasoning_content, "thinking")

    def test_chat_template_kwargs_disabled_by_default(self):
        """默认（enable_thinking=False）也要显式发送关闭思考的 chat_template_kwargs。"""
        captured = {}

        def fake_urlopen(req, timeout):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return _Response({"choices": [{"message": {"content": "ok"}}]})

        client = OpenAICompatibleLLMClient(base_url="http://localhost:8000/v1")
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", fake_urlopen):
            client.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(
            captured["payload"]["chat_template_kwargs"]["enable_thinking"], False
        )
        self.assertNotIn("extra_body", captured["payload"])

    def test_retries_on_rate_limit_then_succeeds(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise _http_error(429)
            return _Response({"choices": [{"message": {"content": "ok"}}]})

        client = OpenAICompatibleLLMClient(base_url="http://localhost:8000/v1", max_retries=2)
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", fake_urlopen), \
             patch("app.infrastructure.llm.openai_compatible.time.sleep"):
            result = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.content, "ok")
        self.assertEqual(len(calls), 2)

    def test_retries_on_network_error_then_succeeds(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise URLError("connection refused")
            return _Response({"choices": [{"message": {"content": "ok"}}]})

        client = OpenAICompatibleLLMClient(base_url="http://localhost:8000/v1", max_retries=2)
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", fake_urlopen), \
             patch("app.infrastructure.llm.openai_compatible.time.sleep"):
            result = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.content, "ok")
        self.assertEqual(len(calls), 2)

    def test_does_not_retry_on_client_error(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(1)
            raise _http_error(400)

        client = OpenAICompatibleLLMClient(base_url="http://localhost:8000/v1", max_retries=2)
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", fake_urlopen), \
             patch("app.infrastructure.llm.openai_compatible.time.sleep"):
            with self.assertRaises(LLMServiceError):
                client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(len(calls), 1)

    def test_zero_retries_does_not_retry_and_keeps_status_code(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(1)
            raise _http_error(503)

        client = OpenAICompatibleLLMClient(base_url="http://localhost:8000/v1", max_retries=0)
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", fake_urlopen):
            with self.assertRaises(LLMServiceError) as ctx:
                client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
