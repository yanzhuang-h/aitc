import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.infrastructure.llm import ModelGateway, ModelRequest, OpenAICompatibleLLMClient, QwenProvider


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return b'{"choices":[{"message":{"content":"{}"}}]}'


class ModelRequestTimeoutTest(unittest.TestCase):
    def test_request_timeout_reaches_transport_without_changing_client_default(self):
        client = OpenAICompatibleLLMClient(timeout_seconds=60)
        gateway = ModelGateway(QwenProvider(client))
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", return_value=_Response()) as network:
            gateway.invoke_sync(ModelRequest(
                messages=[{"role": "user", "content": "bounded request"}],
                timeout_seconds=0.25, max_retries=0,
            ))
            self.assertEqual(network.call_args.kwargs["timeout"], 0.25)
            payload = json.loads(network.call_args.args[0].data)
            self.assertNotIn("timeout_seconds", payload)
            gateway.invoke_sync(ModelRequest(messages=[{"role": "user", "content": "original request"}]))
            self.assertEqual(network.call_args.kwargs["timeout"], 60)
        self.assertEqual(client.timeout_seconds, 60)

    def test_invalid_request_timeout_is_rejected_before_transport(self):
        for value in (0, -1, True, "2", float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    ModelRequest(messages=[{"role": "user", "content": "test"}], timeout_seconds=value)
