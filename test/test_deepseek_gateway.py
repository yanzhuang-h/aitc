"""DeepSeek 的真实 HTTP 请求格式、集中配置和应用装配；无需密钥或外网。"""

from contextlib import contextmanager
from dataclasses import replace
import json
import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.config import ControlAgentSettings, ModelSettings, RuntimeSettings
from app.infrastructure.llm import DeepSeekProvider, ModelGateway, ModelRequest, OpenAICompatibleLLMClient
from runtime.application import create_application
from test.fixtures.v2_baseline_controller import isolated_runtime
from test.test_model_gateway import _Response, _http_error
from test.test_model_gateway_integration import model_application


@contextmanager
def deepseek_application(*, control_enabled=False):
    def create(**kwargs):
        kwargs["settings"] = replace(
            kwargs["settings"], llm_model="deepseek-flash", llm_base_url="https://api.deepseek.com",
            llm_api_key="test-key", control_agent=ControlAgentSettings(enabled=control_enabled),
        )
        return create_application(**kwargs)

    with patch.dict(os.environ, {}, clear=True), patch(
        "test.test_model_gateway_integration.create_application", create,
    ), model_application("deepseek") as app:
        yield app


class DeepSeekGatewayTest(unittest.TestCase):
    def test_transport_uses_bearer_auth_and_deepseek_parameters(self):
        for thinking in (False, True):
            with self.subTest(thinking=thinking):
                client = OpenAICompatibleLLMClient(
                    base_url="https://api.deepseek.com", model="deepseek-flash",
                    api_key="test-key", api_style="deepseek", enable_thinking=thinking,
                )
                gateway = ModelGateway(DeepSeekProvider(client))
                with patch("app.infrastructure.llm.openai_compatible.request.urlopen", return_value=_Response({
                    "choices": [{"message": {"content": '{"tool":"run_control_policy","arguments":{}}'}}],
                })) as network:
                    response = gateway.invoke_sync(ModelRequest(
                        messages=[{"role": "user", "content": "query state"}],
                        timeout_seconds=5, max_retries=0,
                        extra_body={"response_format": {"type": "json_object"}},
                    ))
                req = network.call_args.args[0]
                body = json.loads(req.data)
                self.assertEqual(req.full_url, "https://api.deepseek.com/chat/completions")
                self.assertEqual(req.get_header("Authorization"), "Bearer test-key")
                self.assertEqual(network.call_args.kwargs["timeout"], 5)
                self.assertEqual(body["model"], "deepseek-flash")
                self.assertEqual(body["thinking"], {"type": "enabled" if thinking else "disabled"})
                self.assertEqual(body["response_format"], {"type": "json_object"})
                self.assertNotIn("chat_template_kwargs", body)
                self.assertNotIn("extra_body", body)
                self.assertEqual(json.loads(response.content)["tool"], "run_control_policy")
                self.assertEqual(gateway.provider_name, "deepseek")

    def test_environment_loads_existing_aliases_and_preserves_secret_hiding(self):
        with patch.dict(os.environ, {
            "AITC_LLM_ENABLED": "true", "AITC_MODEL_PROVIDER": "deepseek",
            "AITC_MODEL_NAME": "deepseek-flash", "AITC_MODEL_BASE_URL": "https://api.deepseek.com",
            "AITC_MODEL_API_KEY": "sk-test-private", "AITC_LLM_ENABLE_THINKING": "false",
        }, clear=True), patch("app.config._load_dotenv"):
            settings = RuntimeSettings.from_environment().validate()
        self.assertEqual(settings.model_settings.effective_provider, "deepseek")
        self.assertFalse(settings.llm_enable_thinking)
        self.assertNotIn("sk-test-private", repr(settings))

    def test_active_deepseek_rejects_local_defaults_and_missing_key(self):
        valid = {"provider": "deepseek", "name": "deepseek-flash",
                 "base_url": "https://api.deepseek.com", "api_key": "test-key"}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ModelSettings(**valid).provider, "deepseek")
            for field, value in (("api_key", ""), ("api_key", "EMPTY"),
                                 ("name", "Qwen3-0.6B"), ("base_url", "http://127.0.0.1:8000/v1")):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    ModelSettings(**(valid | {field: value}))
            self.assertEqual(ModelSettings(provider="deepseek", enabled=False).effective_provider, "disabled")

    def test_application_shares_deepseek_gateway_and_disabled_skips_network(self):
        with patch("runtime.application.OpenAICompatibleLLMClient") as factory:
            with deepseek_application() as app:
                self.assertIsInstance(app.model_gateway.provider, DeepSeekProvider)
                self.assertEqual(app.model_gateway.provider_name, "deepseek")
                self.assertIs(app.http_server.agent_harness.qwen_agent.model_gateway, app.model_gateway)
                self.assertEqual(factory.call_args.kwargs["api_style"], "deepseek")
            factory.reset_mock()
            with model_application("deepseek", enabled=False) as app:
                self.assertFalse(app.model_gateway.enabled)
            factory.assert_not_called()

    def test_health_check_uses_deepseek_models_endpoint(self):
        with deepseek_application() as app, patch(
            "app.infrastructure.llm.openai_compatible.request.urlopen",
            return_value=_Response({"data": [{"id": "deepseek-flash"}]}),
        ) as network:
            self.assertEqual(app.model_gateway.check_ready()["data"][0]["id"], "deepseek-flash")
            req = network.call_args.args[0]
            self.assertEqual(req.method, "GET")
            self.assertEqual(req.full_url, "https://api.deepseek.com/models")

    def test_remote_auth_or_timeout_failure_keeps_186_road_control_and_cooldown(self):
        with isolated_runtime(), model_application("disabled") as app:
            app.decision_pipeline.worker_count = 1
            expected = app.decision_pipeline.run_once()
        for failure in (_http_error(401), TimeoutError("remote timed out")):
            with self.subTest(failure=failure), isolated_runtime(), deepseek_application(control_enabled=True) as app, patch(
                "app.infrastructure.llm.openai_compatible.request.urlopen", side_effect=failure,
            ) as network:
                app.decision_pipeline.worker_count = 1
                actual = app.decision_pipeline.run_once()
                self.assertEqual(actual, expected)
                self.assertEqual(len(actual), 186)
                self.assertEqual(network.call_count, 1)
                self.assertEqual(network.call_args.kwargs["timeout"], 2)
                body = json.loads(network.call_args.args[0].data)
                self.assertEqual(body["thinking"], {"type": "disabled"})
                self.assertEqual(body["model"], "deepseek-flash")
                self.assertNotIn("chat_template_kwargs", body)


if __name__ == "__main__":
    unittest.main()
