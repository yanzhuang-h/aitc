import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app.config as config_module
from app.config import RunMode, RuntimeSettings


class RuntimeSettingsTest(unittest.TestCase):
    def setUp(self):
        # 隔离真实 .env，避免测试被本机配置干扰
        self._real_load_dotenv = config_module._load_dotenv
        self._dotenv_patcher = patch.object(config_module, "_load_dotenv", autospec=True)
        self._dotenv_patcher.start()

    def tearDown(self):
        self._dotenv_patcher.stop()

    def test_defaults_preserve_current_runtime_behavior(self):
        settings = RuntimeSettings.from_environment()
        self.assertEqual(settings.tcp_host, "127.0.0.1")
        self.assertEqual(settings.tcp_port, 65432)
        self.assertEqual(settings.http_port, 8088)
        self.assertEqual(settings.decision_interval_seconds, 50)
        self.assertEqual(settings.prediction_hour, 3)

    def test_environment_overrides_runtime_settings(self):
        with patch.dict(os.environ, {
            "AITC_TCP_PORT": "60000",
            "AITC_HTTP_PORT": "9000",
            "AITC_DECISION_INTERVAL_SECONDS": "5.5",
            "AITC_RUNTIME_DATA_DIR": "var/runtime",
            "AITC_LLM_BASE_URL": "http://localhost:8000/v1",
            "AITC_LLM_MODEL": "Qwen3-0.6B",
            "AITC_LLM_MAX_TOKENS": "256",
        }, clear=True):
            settings = RuntimeSettings.from_environment().validate()
        self.assertEqual(settings.tcp_port, 60000)
        self.assertEqual(settings.http_port, 9000)
        self.assertEqual(settings.decision_interval_seconds, 5.5)
        self.assertEqual(settings.runtime_data_dir, Path("var/runtime"))
        self.assertEqual(settings.llm_base_url, "http://localhost:8000/v1")
        self.assertEqual(settings.llm_model, "Qwen3-0.6B")
        self.assertEqual(settings.llm_max_tokens, 256)

    def test_invalid_port_is_rejected(self):
        with self.assertRaises(ValueError):
            RuntimeSettings(tcp_port=0).validate()

    def test_replay_mode_disables_external_background_tasks(self):
        with patch.dict(os.environ, {"AITC_RUN_MODE": "replay"}, clear=True):
            settings = RuntimeSettings.from_environment().validate()
        self.assertEqual(settings.run_mode, RunMode.REPLAY)
        self.assertFalse(settings.enable_config_sync)
        self.assertFalse(settings.enable_prediction_scheduler)

    def test_production_mode_binds_all_interfaces(self):
        with patch.dict(os.environ, {"AITC_RUN_MODE": "production"}, clear=True):
            settings = RuntimeSettings.from_environment().validate()
        self.assertEqual(settings.run_mode, RunMode.PRODUCTION)
        self.assertEqual(settings.tcp_host, "0.0.0.0")
        self.assertEqual(settings.http_host, "0.0.0.0")

    def test_dotenv_file_supports_plain_llm_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "# 本地部署大模型\n"
                'LLM_BASE_URL="http://localhost:8000/v1"\n'
                'LLM_MODEL_ID="Qwen3-0.6B"\n'
                "LLM_API_KEY=vllm\n"
                "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                self._real_load_dotenv(env_file)
                settings = RuntimeSettings.from_environment()
        self.assertEqual(settings.llm_base_url, "http://localhost:8000/v1")
        self.assertEqual(settings.llm_model, "Qwen3-0.6B")
        self.assertEqual(settings.llm_api_key, "vllm")

    def test_plain_llm_env_names_are_supported(self):
        with patch.dict(os.environ, {
            "LLM_BASE_URL": "https://api.deepseek.com/v1",
            "LLM_MODEL_ID": "deepseek-chat",
            "LLM_API_KEY": "sk-test-123",
        }, clear=True):
            settings = RuntimeSettings.from_environment().validate()
        self.assertEqual(settings.llm_base_url, "https://api.deepseek.com/v1")
        self.assertEqual(settings.llm_model, "deepseek-chat")
        self.assertEqual(settings.llm_api_key, "sk-test-123")

    def test_aitc_prefixed_llm_names_take_priority(self):
        with patch.dict(os.environ, {
            "AITC_LLM_BASE_URL": "http://127.0.0.1:8000/v1",
            "LLM_BASE_URL": "https://api.deepseek.com/v1",
            "AITC_LLM_MODEL": "Qwen3-0.6B",
            "LLM_MODEL_ID": "deepseek-chat",
        }, clear=True):
            settings = RuntimeSettings.from_environment()
        self.assertEqual(settings.llm_base_url, "http://127.0.0.1:8000/v1")
        self.assertEqual(settings.llm_model, "Qwen3-0.6B")
