import json
import unittest
from unittest.mock import patch

from app.infrastructure.llm import OpenAICompatibleLLMClient


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


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
        self.assertEqual(result.content, "ok")
        self.assertEqual(result.reasoning_content, "thinking")


if __name__ == "__main__":
    unittest.main()
