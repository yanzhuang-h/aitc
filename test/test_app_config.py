import os
import unittest
from unittest.mock import patch

from app.config import RuntimeSettings


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
        }, clear=True):
            settings = RuntimeSettings.from_environment().validate()
        self.assertEqual(settings.tcp_port, 60000)
        self.assertEqual(settings.http_port, 9000)
        self.assertEqual(settings.decision_interval_seconds, 5.5)
        self.assertEqual(str(settings.runtime_data_dir), "var\\runtime")

    def test_invalid_port_is_rejected(self):
        with self.assertRaises(ValueError):
            RuntimeSettings(tcp_port=0).validate()
