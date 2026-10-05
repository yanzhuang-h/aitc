"""Model Gateway contracts, transport behavior, and shared-call isolation."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import math
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from pydantic import ValidationError

from app.infrastructure.llm import (
    ChatCompletionResult,
    DisabledProvider,
    ModelDisabledError,
    ModelGateway,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    MockProvider,
    OpenAICompatibleLLMClient,
    QwenProvider,
    as_model_gateway,
)


def _request(content="hello", **kwargs):
    return ModelRequest(
        messages=[ModelMessage(role="user", content=content)], **kwargs
    )


class _Response:
    def __init__(self, payload, *, encoded=False):
        self.payload = payload if encoded else json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class _ErrorBody:
    def read(self):
        return b'{"error": "unavailable"}'

    def close(self):
        pass


def _http_error(status_code):
    return HTTPError(
        "http://localhost:8000/v1/chat/completions",
        status_code,
        "error",
        {},
        _ErrorBody(),
    )


class _ChatClient:
    model = "fake-qwen"
    base_url = "http://localhost:8000/v1"

    def __init__(self, response=None, error=None):
        self.response = response or ChatCompletionResult("answer")
        self.error = error
        self.calls = []
        self.health_calls = 0

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.error is not None:
            raise self.error
        return self.response

    def list_models(self):
        self.health_calls += 1
        return {"data": [{"id": self.model}]}


class ModelRequestContractTest(unittest.TestCase):
    def test_messages_and_sampling_options_are_typed(self):
        request = ModelRequest(
            messages=[{"role": "system", "content": "stay precise"},
                      {"role": "user", "content": "hello"}],
            temperature=0.0,
            top_p=1.0,
            max_tokens=16,
            max_retries=0,
            extra_body={"request_metadata": {"road": "1300086"}},
        )
        self.assertIsInstance(request.messages[0], ModelMessage)
        self.assertEqual(request.max_tokens, 16)
        self.assertEqual(request.max_retries, 0)

    def test_messages_reject_unsupported_roles_and_non_text_content(self):
        for message in (
            {"role": "human", "content": "hello"},
            {"role": "user", "content": 12},
            {"role": "user", "content": None},
        ):
            with self.subTest(message=message), self.assertRaises(ValidationError):
                ModelRequest(messages=[message])

    def test_sampling_options_reject_strings_nonfinite_and_out_of_range(self):
        invalid = {
            "temperature": ("0.7", True, math.nan, math.inf, -0.01, 2.01),
            "top_p": ("0.8", True, math.nan, math.inf, -0.01, 1.01),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value), \
                     self.assertRaises(ValidationError):
                    _request(**{field: value})

    def test_token_and_retry_limits_are_strict_integers(self):
        invalid = {
            "max_tokens": (0, -1, True, 2.5, "16"),
            "max_retries": (-1, True, 2.5, "1"),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value), \
                     self.assertRaises(ValidationError):
                    _request(**{field: value})

    def test_response_contract_does_not_coerce_content(self):
        for content in (None, 123, ["answer"]):
            with self.subTest(content=content), self.assertRaises(ValidationError):
                ModelResponse(content=content)
        self.assertEqual(ModelResponse(content="").content, "")


class QwenModelGatewayTest(unittest.TestCase):
    def test_typed_request_reaches_real_transport_and_response_is_typed(self):
        captured = {}

        def urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _Response({
                "id": "completion-1",
                "choices": [{"message": {
                    "content": "answer", "reasoning_content": "reason"
                }}],
            })

        client = OpenAICompatibleLLMClient(
            base_url="http://localhost:8000/v1/", model="Qwen3-0.6B",
            api_key="test-key", timeout_seconds=7, enable_thinking=True,
        )
        gateway = ModelGateway(QwenProvider(client))
        request = _request(
            temperature=0.25, top_p=0.9, max_tokens=23,
            extra_body={"seed": 17}, max_retries=0,
        )
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", urlopen):
            response = gateway.invoke_sync(request)

        self.assertIsInstance(response, ModelResponse)
        self.assertEqual(response.content, "answer")
        self.assertEqual(response.reasoning_content, "reason")
        self.assertEqual(response.raw["id"], "completion-1")
        self.assertEqual(captured["url"], "http://localhost:8000/v1/chat/completions")
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["headers"]["Content-type"], "application/json")
        body = captured["body"]
        self.assertEqual(body["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(body["model"], "Qwen3-0.6B")
        self.assertEqual(body["temperature"], 0.25)
        self.assertEqual(body["top_p"], 0.9)
        self.assertEqual(body["max_tokens"], 23)
        self.assertEqual(body["extra_body"], {"enable_thinking": True, "seed": 17})
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": True})
        self.assertTrue(gateway.enabled)
        self.assertEqual(gateway.provider_name, "qwen")
        self.assertEqual(gateway.model, "Qwen3-0.6B")
        self.assertEqual(gateway.base_url, "http://localhost:8000/v1")

    def test_default_transport_options_keep_thinking_disabled(self):
        captured = {}

        def urlopen(request, timeout):
            captured.update(json.loads(request.data))
            return _Response({"choices": [{"message": {"content": "answer"}}]})

        gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(default_max_tokens=42)))
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", urlopen):
            gateway.invoke_sync(_request())
        self.assertEqual(captured["max_tokens"], 42)
        self.assertEqual(captured["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("extra_body", captured)

    def test_calls_do_not_implicitly_probe_model_readiness(self):
        client = _ChatClient()
        gateway = ModelGateway(QwenProvider(client))
        gateway.invoke_sync(_request())
        self.assertEqual(client.health_calls, 0)
        gateway.check_ready()
        self.assertEqual(client.health_calls, 1)

    def test_legacy_client_adapter_is_idempotent_and_uses_injected_client(self):
        client = _ChatClient()
        gateway = as_model_gateway(client)
        self.assertIs(as_model_gateway(gateway), gateway)
        self.assertEqual(gateway.invoke_sync(_request()).content, "answer")
        self.assertEqual(len(client.calls), 1)

    def test_readiness_uses_models_endpoint_and_reports_service_failure(self):
        client = OpenAICompatibleLLMClient(api_key="health-key", max_retries=2)
        gateway = ModelGateway(QwenProvider(client))
        captured = {}

        def urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.method
            captured["headers"] = dict(request.header_items())
            return _Response({"data": [{"id": "Qwen3-0.6B"}]})

        with patch("app.infrastructure.llm.openai_compatible.request.urlopen", urlopen):
            models = gateway.check_ready()
        self.assertEqual(models["data"][0]["id"], "Qwen3-0.6B")
        self.assertEqual(captured["url"], "http://127.0.0.1:8000/v1/models")
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer health-key")
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen",
                   side_effect=_http_error(503)) as urlopen_mock, \
             self.assertRaises(ModelUnavailableError) as raised:
            gateway.check_ready()
        self.assertEqual(urlopen_mock.call_count, 1)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIsNotNone(raised.exception.__cause__)

    def test_readiness_rejects_malformed_http_200_model_lists_without_retry(self):
        payloads = (
            None, [], {"error": "not actually ready"},
            {"data": "wrong-shape"},
            {"data": [{"id": 123}]},
            {"data": [{"id": ""}]},
        )
        for payload in payloads:
            gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(max_retries=2)))
            with self.subTest(payload=payload), \
                 patch("app.infrastructure.llm.openai_compatible.request.urlopen",
                       return_value=_Response(payload)) as urlopen, \
                 self.assertRaises(ModelResponseError) as raised:
                gateway.check_ready()
            self.assertEqual(urlopen.call_count, 1)
            self.assertIsInstance(raised.exception.__cause__, ValidationError)

    def test_readiness_accepts_empty_lists_and_other_valid_model_ids(self):
        payloads = (
            {"data": []},
            {"data": [{"id": "other-model", "owner": "service"}],
             "object": "list", "additional_metadata": {"version": 1}},
        )
        for payload in payloads:
            gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(model="configured-model")))
            with self.subTest(payload=payload), \
                 patch("app.infrastructure.llm.openai_compatible.request.urlopen",
                       return_value=_Response(payload)) as urlopen:
                response = gateway.check_ready()
            self.assertEqual(response["data"], payload["data"])
            self.assertEqual(urlopen.call_count, 1)

    def test_retry_count_is_owned_by_transport_without_gateway_multiplier(self):
        for status_code in (429, 500, 503):
            attempts = []

            def urlopen(request, timeout):
                attempts.append(1)
                if len(attempts) <= 2:
                    raise _http_error(status_code)
                return _Response({"choices": [{"message": {"content": "recovered"}}]})

            gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(max_retries=2)))
            with self.subTest(status_code=status_code), \
                 patch("app.infrastructure.llm.openai_compatible.request.urlopen", urlopen), \
                 patch("app.infrastructure.llm.openai_compatible.time.sleep"):
                response = gateway.invoke_sync(_request())
            self.assertEqual(response.content, "recovered")
            self.assertEqual(len(attempts), 3)

    def test_request_zero_retry_preserves_http_status_and_exception_chain(self):
        gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(max_retries=2)))
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen",
                   side_effect=_http_error(503)) as urlopen, \
             self.assertRaises(ModelUnavailableError) as raised:
            gateway.invoke_sync(_request(max_retries=0))
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIsNotNone(raised.exception.__cause__)
        self.assertIsInstance(raised.exception.__cause__.__cause__, HTTPError)

    def test_http_client_error_is_not_retried(self):
        gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(max_retries=2)))
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen",
                   side_effect=_http_error(400)) as urlopen, \
             self.assertRaises(ModelGatewayError) as raised:
            gateway.invoke_sync(_request())
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(raised.exception.status_code, 400)

    def test_network_failure_is_classified_after_transport_retry_budget(self):
        gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(max_retries=1)))
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen",
                   side_effect=URLError("connection refused")) as urlopen, \
             patch("app.infrastructure.llm.openai_compatible.time.sleep"), \
             self.assertRaises(ModelUnavailableError) as raised:
            gateway.invoke_sync(_request())
        self.assertEqual(urlopen.call_count, 2)
        self.assertIsNone(raised.exception.status_code)
        self.assertIsNotNone(raised.exception.__cause__)

    def test_direct_and_wrapped_socket_timeouts_are_classified(self):
        for error in (TimeoutError("socket deadline"), URLError(TimeoutError("socket deadline"))):
            gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(max_retries=0)))
            with self.subTest(error=error), \
                 patch("app.infrastructure.llm.openai_compatible.request.urlopen", side_effect=error), \
                 self.assertRaises(ModelTimeoutError) as raised:
                gateway.invoke_sync(_request())
            self.assertIsNotNone(raised.exception.__cause__)

    def test_malformed_service_json_is_a_response_error_without_retry(self):
        payloads = (
            None, [], {}, {"choices": []},
            {"choices": "wrong-shape"},
            {"choices": [{"message": []}]},
            {"choices": [{"message": {"content": 12}}]},
            {"choices": [{"message": {"content": "ok", "reasoning_content": 12}}]},
        )
        for payload in payloads:
            gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient(max_retries=2)))
            with self.subTest(payload=payload), \
                 patch("app.infrastructure.llm.openai_compatible.request.urlopen",
                       return_value=_Response(payload)) as urlopen, \
                 self.assertRaises(ModelResponseError) as raised:
                gateway.invoke_sync(_request())
            self.assertEqual(urlopen.call_count, 1)
            self.assertIsNotNone(raised.exception.__cause__)

    def test_non_json_and_non_utf8_service_bodies_are_response_errors(self):
        for body in (b"not-json", b"\xff"):
            gateway = ModelGateway(QwenProvider(OpenAICompatibleLLMClient()))
            with self.subTest(body=body), \
                 patch("app.infrastructure.llm.openai_compatible.request.urlopen",
                       return_value=_Response(body, encoded=True)), \
                 self.assertRaises(ModelResponseError) as raised:
                gateway.invoke_sync(_request())
            self.assertIsNotNone(raised.exception.__cause__)

    def test_programming_errors_from_injected_client_are_not_hidden(self):
        for error in (RuntimeError("bug"), KeyError("missing"),
                      TypeError("wrong argument"), AssertionError("contract bug")):
            gateway = ModelGateway(QwenProvider(_ChatClient(error=error)))
            with self.subTest(error=error), self.assertRaises(type(error)) as raised:
                gateway.invoke_sync(_request())
            self.assertIs(raised.exception, error)

    def test_unvalidated_request_is_rejected_before_provider_call(self):
        client = _ChatClient()
        request = ModelRequest.model_construct(
            messages=[ModelMessage.model_construct(role="user", content=12)]
        )
        with self.assertRaises(ValidationError):
            ModelGateway(QwenProvider(client)).invoke_sync(request)
        self.assertEqual(client.calls, [])

    def test_injected_client_response_is_strictly_validated(self):
        client = _ChatClient(response=ChatCompletionResult(content=12))
        with self.assertRaises(ModelResponseError):
            ModelGateway(QwenProvider(client)).invoke_sync(_request())

    def test_provider_cannot_mutate_the_request_or_share_response_raw(self):
        raw = {"metadata": {"road": "original"}}

        class MutatingClient(_ChatClient):
            def chat(self, messages, **kwargs):
                messages[0]["content"] = "mutated"
                kwargs["extra_body"]["metadata"]["road"] = "mutated"
                return ChatCompletionResult("answer", raw=raw)

        request = _request(extra_body={"metadata": {"road": "original"}})
        gateway = ModelGateway(QwenProvider(MutatingClient()))
        first = gateway.invoke_sync(request)
        first.raw["metadata"]["road"] = "returned-mutation"
        second = gateway.invoke_sync(request)
        self.assertEqual(request.messages[0].content, "hello")
        self.assertEqual(request.extra_body["metadata"]["road"], "original")
        self.assertEqual(raw["metadata"]["road"], "original")
        self.assertEqual(second.raw["metadata"]["road"], "original")

    def test_shared_gateway_keeps_concurrent_requests_isolated(self):
        barrier = threading.Barrier(4)

        class EchoClient(_ChatClient):
            def chat(self, messages, **kwargs):
                barrier.wait(timeout=5)
                return ChatCompletionResult(
                    content=messages[0]["content"],
                    raw={"extra_body": kwargs["extra_body"]},
                )

        gateway = ModelGateway(QwenProvider(EchoClient()))
        requests = [_request(str(i), extra_body={"slot": i}) for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(gateway.invoke_sync, requests))
        self.assertEqual([response.content for response in responses], ["0", "1", "2", "3"])
        self.assertEqual([response.raw["extra_body"]["slot"] for response in responses], list(range(4)))
        responses[0].raw["extra_body"]["slot"] = -1
        self.assertEqual(requests[0].extra_body["slot"], 0)
        self.assertEqual(responses[1].raw["extra_body"]["slot"], 1)


class DisabledAndMockGatewayTest(unittest.TestCase):
    def test_disabled_mode_never_constructs_or_contacts_a_client(self):
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen") as urlopen, \
             patch.object(OpenAICompatibleLLMClient, "__init__", side_effect=AssertionError("client created")):
            gateway = ModelGateway(DisabledProvider())
            self.assertFalse(gateway.enabled)
            self.assertEqual(gateway.provider_name, "disabled")
            gateway.check_ready()
            with self.assertRaises(ModelDisabledError):
                gateway.invoke_sync(_request())
        urlopen.assert_not_called()

    def test_default_mock_returns_empty_content_without_network(self):
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen") as urlopen:
            gateway = ModelGateway(MockProvider())
            gateway.check_ready()
            self.assertEqual(gateway.provider_name, "mock")
            self.assertEqual(gateway.model, "mock")
            for _ in range(3):
                response = gateway.invoke_sync(_request())
                self.assertEqual(response.content, "")
                self.assertEqual(response.raw, {})
        urlopen.assert_not_called()

    def test_mock_script_is_finite_and_preserves_input_and_output_isolation(self):
        source = ModelResponse(content="first", raw={"nested": {"value": 1}})
        gateway = ModelGateway(MockProvider([source, ModelResponse(content="second")]))
        source.raw["nested"]["value"] = 100
        first = gateway.invoke_sync(_request())
        self.assertEqual(first.raw["nested"]["value"], 1)
        first.raw["nested"]["value"] = 200
        second = gateway.invoke_sync(_request())
        self.assertEqual(second.content, "second")
        self.assertEqual(second.raw, {})
        with self.assertRaises(ModelGatewayError):
            gateway.invoke_sync(_request())

    def test_explicit_empty_mock_script_is_exhausted_immediately(self):
        gateway = ModelGateway(MockProvider([]))
        with self.assertRaises(ModelGatewayError):
            gateway.invoke_sync(_request())

    def test_mock_validates_constructed_response_before_serving_it(self):
        with self.assertRaises(ValidationError):
            MockProvider([ModelResponse.model_construct(content=123)])

    def test_shared_mock_consumes_each_scripted_response_once(self):
        gateway = ModelGateway(MockProvider([
            ModelResponse(content=str(i)) for i in range(20)
        ]))
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(gateway.invoke_sync, [_request()] * 20))
        self.assertEqual({response.content for response in responses}, {str(i) for i in range(20)})
        with self.assertRaises(ModelGatewayError):
            gateway.invoke_sync(_request())


class AsyncModelGatewayTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_invoke_returns_the_typed_response(self):
        gateway = ModelGateway(MockProvider([ModelResponse(content="async-answer")]))
        response = await gateway.invoke(_request())
        self.assertIsInstance(response, ModelResponse)
        self.assertEqual(response.content, "async-answer")

    async def test_sync_adapter_can_run_inside_an_active_event_loop(self):
        gateway = ModelGateway(MockProvider())
        self.assertEqual(gateway.invoke_sync(_request()).content, "")

    async def test_async_request_is_copied_before_waiting_for_an_available_worker(self):
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        occupied = threading.Event()
        release = threading.Event()

        def occupy_worker():
            occupied.set()
            release.wait(timeout=3)

        class EchoClient(_ChatClient):
            def chat(self, messages, **kwargs):
                return ChatCompletionResult(
                    messages[0]["content"], raw={"metadata": kwargs["extra_body"]}
                )

        occupying_task = loop.run_in_executor(None, occupy_worker)
        request = _request("original", extra_body={"nested": {"value": 1}})
        gateway = ModelGateway(QwenProvider(EchoClient()))
        task = None
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
                if occupied.is_set():
                    break
            self.assertTrue(occupied.is_set())
            task = asyncio.create_task(gateway.invoke(request))
            await asyncio.sleep(0)
            request.messages[0].content = "changed-after-submission"
            request.extra_body["nested"]["value"] = 99
        finally:
            release.set()
            await occupying_task
        response = await task
        self.assertEqual(response.content, "original")
        self.assertEqual(response.raw["metadata"]["nested"]["value"], 1)

    async def test_blocking_transport_does_not_block_the_event_loop(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingClient(_ChatClient):
            def chat(self, messages, **kwargs):
                entered.set()
                if not release.wait(timeout=3):
                    raise TimeoutError("test failed to release transport")
                return ChatCompletionResult("answer")

        gateway = ModelGateway(QwenProvider(BlockingClient()))
        task = asyncio.create_task(gateway.invoke(_request()))
        ticks = 0
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
                ticks += 1
                if entered.is_set():
                    break
            self.assertTrue(entered.is_set())
            self.assertFalse(task.done())
            await asyncio.sleep(0)
            self.assertGreater(ticks, 0)
        finally:
            release.set()
            response = await task
        self.assertEqual(response.content, "answer")

    async def test_disabled_async_mode_raises_without_network(self):
        gateway = ModelGateway(DisabledProvider())
        with patch("app.infrastructure.llm.openai_compatible.request.urlopen") as urlopen:
            with self.assertRaises(ModelDisabledError):
                await gateway.invoke(_request())
        urlopen.assert_not_called()

    async def test_cancellation_is_preserved_while_running_transport_can_finish(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingClient(_ChatClient):
            def chat(self, messages, **kwargs):
                entered.set()
                if not release.wait(timeout=3):
                    raise TimeoutError("test failed to release transport")
                return ChatCompletionResult("late-answer")

        gateway = ModelGateway(QwenProvider(BlockingClient()))
        task = asyncio.create_task(gateway.invoke(_request()))
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
                if entered.is_set():
                    break
            self.assertTrue(entered.is_set())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(task.cancelled())
        finally:
            release.set()
            if not task.done():
                await task


if __name__ == "__main__":
    unittest.main()
