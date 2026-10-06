import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.config import ControlAgentSettings, RuntimeSettings


class ControlAgentSettingsTest(unittest.TestCase):
    def test_defaults_keep_periodic_model_calls_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = RuntimeSettings().control_agent
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.max_model_calls, 3)
        self.assertEqual(settings.timeout_seconds, 2)
        self.assertEqual(settings.failure_cooldown_seconds, 30)

    def test_environment_budget_is_loaded_centrally(self):
        with patch.dict(os.environ, {
            "AITC_CONTROL_AGENT_ENABLED": "true",
            "AITC_CONTROL_AGENT_MAX_MODEL_CALLS": "4",
            "AITC_CONTROL_AGENT_TIMEOUT_SECONDS": "1.5",
            "AITC_CONTROL_AGENT_MAX_CONTEXT_CHARS": "8000",
            "AITC_CONTROL_AGENT_FAILURE_COOLDOWN_SECONDS": "20",
        }, clear=True), patch("app.config._load_dotenv"):
            settings = RuntimeSettings.from_environment().control_agent
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.max_model_calls, 4)
        self.assertEqual(settings.timeout_seconds, 1.5)
        self.assertEqual(settings.max_context_chars, 8000)
        self.assertEqual(settings.failure_cooldown_seconds, 20)

    def test_explicit_settings_remain_independent_of_environment_changes(self):
        with patch.dict(os.environ, {}, clear=True):
            configured = ControlAgentSettings(enabled=True, max_model_calls=2)
            runtime = RuntimeSettings(control_agent=configured)
        with patch.dict(os.environ, {"AITC_CONTROL_AGENT_ENABLED": "false"}):
            self.assertIs(runtime.control_agent, configured)
            self.assertTrue(runtime.control_agent.enabled)

    def test_invalid_types_and_unbounded_budgets_are_rejected(self):
        cases = (
            {"enabled": "true"}, {"enabled": 1},
            {"max_model_calls": True}, {"max_model_calls": 0}, {"max_model_calls": 7},
            {"timeout_seconds": True}, {"timeout_seconds": 0},
            {"timeout_seconds": float("inf")}, {"timeout_seconds": 31},
            {"max_context_chars": True}, {"max_context_chars": 1999},
            {"failure_cooldown_seconds": 0}, {"failure_cooldown_seconds": float("nan")},
        )
        for values in cases:
            with self.subTest(values=values), patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ValidationError):
                    ControlAgentSettings(**values)
