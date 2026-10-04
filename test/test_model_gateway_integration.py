"""模型装配与真实周期控制隔离，HTTP Agent 共用网关的回归。"""

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from app.config import RuntimeSettings
from app.infrastructure.llm import (
    DisabledProvider, ModelDisabledError, ModelGateway, ModelRequest, ModelResponse,
    ModelResponseError, ModelTimeoutError, ModelUnavailableError, MockProvider, QwenProvider,
)
from runtime.application import create_application
from test.fixtures.v2_baseline_controller import isolated_runtime


@contextmanager
def model_application(provider="qwen", *, enabled=True, required=False):
    with tempfile.TemporaryDirectory(prefix="aitc-model-gateway-") as directory:
        root = Path(directory)
        settings = RuntimeSettings(
            model_provider=provider, llm_enabled=enabled, llm_required=required,
            runtime_data_dir=root / "history", runtime_output_dir=root / "output",
            prediction_data_dir=root / "prediction", control_snapshot_dir=root / "snapshot",
            enable_config_sync=False, enable_prediction_scheduler=False,
            enable_experience_pool_scheduler=False,
        )
        app = create_application(settings=settings)
        try:
            yield app
        finally:
            app.stop()


@contextmanager
def startup_without_servers(app):
    with patch.object(app.http_server, "start"), patch.object(
        app.tcp_server, "start_broadcast_thread",
    ), patch.object(app, "_run_decision_loop"):
        yield


class ModelGatewayIntegrationTest(unittest.TestCase):
    def test_qwen_composition_and_all_agents_share_one_gateway(self):
        with model_application() as app:
            gateway = app.model_gateway
            self.assertIsInstance(gateway, ModelGateway)
            self.assertIsInstance(gateway.provider, QwenProvider)
            self.assertIs(app.llm_client, gateway)
            self.assertEqual(gateway.model, RuntimeSettings.llm_model)
            harness = app.http_server.agent_harness
            for agent in (harness.qwen_agent, harness.qwen_tool_router_agent,
                          harness.control_process_agent):
                self.assertIs(agent.model_gateway, gateway)
                self.assertIs(agent.llm_client, gateway)

    def test_disabled_flag_and_provider_never_construct_or_check_network_client(self):
        for provider, enabled in (("qwen", False), ("mock", False), ("disabled", True)):
            with self.subTest(provider=provider, enabled=enabled), patch(
                "runtime.application.OpenAICompatibleLLMClient",
                side_effect=AssertionError("disabled must not construct a client"),
            ), model_application(provider, enabled=enabled, required=True) as app:
                self.assertIsInstance(app.model_gateway.provider, DisabledProvider)
                self.assertIsNone(app.llm_client)
                self.assertFalse(app.llm_required)
                harness = app.http_server.agent_harness
                self.assertIsNone(harness.qwen_agent)
                self.assertIsNone(harness.qwen_tool_router_agent)
                self.assertIsNone(harness.control_process_agent)
                with startup_without_servers(app), patch.object(
                    app.model_gateway, "check_ready", side_effect=AssertionError("disabled health"),
                ) as ready:
                    app.start()
                    ready.assert_not_called()
                with self.assertRaises(ModelDisabledError):
                    app.model_gateway.invoke_sync(ModelRequest(
                        messages=[{"role": "user", "content": "test"}],
                    ))

    def test_mock_startup_and_symbolic_queries_need_no_model_service(self):
        with patch("runtime.application.OpenAICompatibleLLMClient") as client, patch(
            "app.infrastructure.llm.openai_compatible.request.urlopen",
            side_effect=AssertionError("mock must not use a model service"),
        ) as network, model_application("mock", required=True) as app:
            self.assertIsInstance(app.model_gateway.provider, MockProvider)
            self.assertEqual(app.model_gateway.model, "mock")
            with startup_without_servers(app):
                app.start()
            response = app.http_server.agent_harness.handle("symbolic", {
                "action": "results.latest", "arguments": {"limit": 1},
            })
            self.assertEqual(response["result"]["status"], "ok")
            client.assert_not_called()
            network.assert_not_called()

    def test_both_qwen_agents_use_gateway_for_routing_and_summary(self):
        cases = (
            ("agent.signal_timing", {"action": "signal.timing.single", "arguments": {}}),
            ("agent.tools", {"tool_name": "query_latest_results", "arguments": {"limit": 1}}),
        )
        with model_application("mock") as app:
            for intent, choice in cases:
                with self.subTest(intent=intent):
                    app.model_gateway.provider = MockProvider([
                        ModelResponse(content=json.dumps(choice)),
                        ModelResponse(content="已通过网关完成查询。"),
                    ])
                    with patch.object(
                        app.model_gateway, "invoke_sync", wraps=app.model_gateway.invoke_sync,
                    ) as invoke:
                        response = app.http_server.agent_harness.handle(intent, {
                            "request_text": "查看路口结果", "cross_id": "1300068",
                        })
                    self.assertEqual(response["result"]["status"], "ok")
                    self.assertEqual(response["result"]["summary"], "已通过网关完成查询。")
                    self.assertEqual(invoke.call_count, 2)
                    self.assertEqual(invoke.call_args_list[0].args[0].temperature, 0.2)
                    self.assertEqual(invoke.call_args_list[1].args[0].temperature, 0.4)

    def test_control_process_uses_gateway_but_rules_still_compute_every_step(self):
        with model_application("mock") as app:
            app.model_gateway.provider = MockProvider([
                ModelResponse(content="该步已由规则完成。") for _ in range(10)
            ])
            with patch.object(
                app.model_gateway, "invoke_sync", wraps=app.model_gateway.invoke_sync,
            ) as invoke:
                result = app.http_server.agent_harness.handle("control_process", {
                    "cross_id": "1300068",
                })
            self.assertEqual(invoke.call_count, 10)
            self.assertEqual(len(result["result"]["data"]["steps"]), 10)
            self.assertTrue(all(step["data"] for step in result["result"]["data"]["steps"]))

    def test_unavailable_qwen_can_start_and_does_not_change_186_road_control(self):
        outputs = []
        for provider in ("disabled", "mock", "qwen"):
            with self.subTest(provider=provider), isolated_runtime(), patch(
                "app.infrastructure.llm.openai_compatible.request.urlopen",
                side_effect=URLError("no model server"),
            ) as network, model_application(provider) as app, startup_without_servers(app):
                app.start()
                app.decision_pipeline.worker_count = 1
                outputs.append(app.decision_pipeline.run_once())
                self.assertEqual(len(outputs[-1]), 186)
                self.assertEqual(outputs[-1], app.decision_pipeline.result_warehouse.snapshot())
                # qwen 只有启动检查，其失败不引入周期图中的模型调用。
                self.assertEqual(network.call_count, 1 if provider == "qwen" else 0)
        self.assertEqual(outputs[1], outputs[0])
        self.assertEqual(outputs[2], outputs[0])

    def test_failed_or_timed_out_model_invoke_does_not_pollute_control(self):
        def run_round(failure):
            with isolated_runtime(), model_application() as app:
                if failure is not None:
                    with patch.object(app.model_gateway.provider.client, "chat", side_effect=failure):
                        with self.assertRaises((ModelTimeoutError, ModelUnavailableError)):
                            app.model_gateway.invoke_sync(ModelRequest(
                                messages=[{"role": "user", "content": "read state"}],
                            ))
                app.decision_pipeline.worker_count = 1
                return app.decision_pipeline.run_once()

        expected = run_round(None)
        for failure in (TimeoutError("socket read expired"), URLError("no model server")):
            with self.subTest(failure=failure):
                self.assertEqual(run_round(failure), expected)

    def test_qwen_required_unavailable_or_invalid_models_blocks_before_servers_start(self):
        for models in (None, [], {"error": "not ready"}):
            with self.subTest(models=models), model_application(required=True) as app, patch.object(
                app.model_gateway.provider.client, "list_models", return_value=models,
            ), patch.object(app.http_server, "start") as http, patch.object(
                app.tcp_server, "start_broadcast_thread",
            ) as tcp:
                with self.assertRaises(RuntimeError) as error:
                    app.start()
                self.assertIsInstance(error.exception.__cause__, ModelResponseError)
                http.assert_not_called()
                tcp.assert_not_called()
                self.assertIsNone(app._decision_thread)

        with model_application(required=True) as app, patch.object(
            app.model_gateway.provider.client, "list_models", side_effect=URLError("unavailable"),
        ), patch.object(app.http_server, "start") as http:
            with self.assertRaises(RuntimeError) as error:
                app.start()
            self.assertIsInstance(error.exception.__cause__, ModelUnavailableError)
            http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
