import os
from pathlib import Path
import unittest
from unittest.mock import patch

from app.config import RunMode, RuntimeSettings


class RuntimeSettingsTest(unittest.TestCase):
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
