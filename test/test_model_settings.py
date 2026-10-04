import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from pydantic_settings import BaseSettings

import app.config as config_module
from app.config import ModelSettings, RuntimeSettings


class ModelSettingsTest(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {}, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self._dotenv = patch("app.config._load_dotenv")
        self._dotenv.start()
        self.addCleanup(self._dotenv.stop)

    def test_runtime_defaults_use_model_defaults(self):
        self.assertIsInstance(ModelSettings(), BaseSettings)
        runtime_fields = {
            "enabled": "llm_enabled", "provider": "model_provider",
            "name": "llm_model", "base_url": "llm_base_url", "api_key": "llm_api_key",
            "timeout_seconds": "llm_timeout_seconds", "max_tokens": "llm_max_tokens",
            "enable_thinking": "llm_enable_thinking", "required": "llm_required",
        }
        runtime = RuntimeSettings()
        for name, legacy_name in runtime_fields.items():
            with self.subTest(name=name):
                default = ModelSettings.model_fields[name].default
                self.assertEqual(getattr(RuntimeSettings, legacy_name), default)
                self.assertEqual(getattr(runtime, legacy_name), default)
                self.assertEqual(getattr(runtime.model_settings, name), default)

    def test_name_url_and_key_aliases_keep_priority_and_skip_blank_values(self):
        aliases = {
            "name": ("AITC_MODEL_NAME", "AITC_LLM_MODEL", "MODEL_NAME", "LLM_MODEL_ID"),
            "base_url": ("AITC_MODEL_BASE_URL", "AITC_LLM_BASE_URL", "MODEL_BASE_URL", "LLM_BASE_URL"),
            "api_key": ("AITC_MODEL_API_KEY", "AITC_LLM_API_KEY", "MODEL_API_KEY", "LLM_API_KEY"),
        }
        for name, keys in aliases.items():
            for priority in range(len(keys)):
                env = {key: f" value-{index} " for index, key in enumerate(keys)}
                env.update({key: " \t " for key in keys[:priority]})
                with self.subTest(name=name, priority=priority), patch.dict(os.environ, env, clear=True):
                    self.assertEqual(getattr(ModelSettings(), name), f"value-{priority}")
                    self.assertEqual(getattr(RuntimeSettings.from_environment().model_settings, name), f"value-{priority}")

    def test_provider_and_enabled_aliases_determine_effective_provider(self):
        with patch.dict(os.environ, {
            "AITC_MODEL_PROVIDER": "mock", "MODEL_PROVIDER": "qwen",
            "AITC_LLM_ENABLED": "off", "LLM_ENABLED": "true",
        }, clear=True):
            settings = RuntimeSettings.from_environment().model_settings
        self.assertEqual(settings.provider, "mock")
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.effective_provider, "disabled")
        with patch.dict(os.environ, {
            "AITC_MODEL_PROVIDER": " ", "MODEL_PROVIDER": "disabled",
            "AITC_LLM_ENABLED": " ", "LLM_ENABLED": "on",
        }, clear=True):
            settings = ModelSettings()
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.effective_provider, "disabled")

    def test_legacy_numeric_and_boolean_environment_names_keep_aitc_priority(self):
        with patch.dict(os.environ, {
            "AITC_LLM_TIMEOUT_SECONDS": " 2.5 ", "LLM_TIMEOUT_SECONDS": "8",
            "AITC_LLM_MAX_TOKENS": " 64 ", "LLM_MAX_TOKENS": "128",
            "AITC_LLM_ENABLE_THINKING": "yes", "LLM_ENABLE_THINKING": "no",
            "AITC_LLM_REQUIRED": "1", "LLM_REQUIRED": "0",
        }, clear=True):
            settings = ModelSettings()
        self.assertEqual(settings.timeout_seconds, 2.5)
        self.assertEqual(settings.max_tokens, 64)
        self.assertTrue(settings.enable_thinking)
        self.assertTrue(settings.required)
        with patch.dict(os.environ, {
            "LLM_TIMEOUT_SECONDS": "3", "LLM_MAX_TOKENS": "32",
            "LLM_ENABLE_THINKING": "OFF", "LLM_REQUIRED": "FALSE",
        }, clear=True):
            settings = RuntimeSettings.from_environment().model_settings
        self.assertEqual(settings.timeout_seconds, 3.0)
        self.assertEqual(settings.max_tokens, 32)
        self.assertFalse(settings.enable_thinking)
        self.assertFalse(settings.required)

    def test_explicit_runtime_settings_are_isolated_from_environment_changes(self):
        runtime = RuntimeSettings(
            model_provider="mock", llm_enabled=True, llm_model="fixed-model",
            llm_base_url="", llm_api_key="private-key", llm_timeout_seconds=0,
            llm_max_tokens=0, llm_enable_thinking=True, llm_required=True,
        )
        with patch.dict(os.environ, {
            "AITC_MODEL_PROVIDER": "invalid", "AITC_LLM_ENABLED": "invalid",
            "AITC_MODEL_NAME": "changed-model", "AITC_MODEL_API_KEY": "changed-key",
        }, clear=True):
            self.assertIs(runtime.validate(), runtime)
            first = runtime.model_settings
        self.assertEqual(first, runtime.model_settings)
        self.assertEqual(first.name, "fixed-model")
        self.assertEqual(first.api_key, "private-key")
        self.assertEqual(first.effective_provider, "mock")
        self.assertEqual(first.timeout_seconds, 0)
        self.assertEqual(first.max_tokens, 0)
        self.assertTrue(first.enable_thinking)
        self.assertTrue(first.required)

    def test_explicit_model_settings_override_environment_aliases(self):
        with patch.dict(os.environ, {
            "AITC_MODEL_PROVIDER": "invalid", "AITC_MODEL_NAME": "from-environment",
            "AITC_LLM_ENABLED": "invalid",
        }, clear=True):
            settings = ModelSettings(provider="mock", name="from-kwargs", enabled=True)
        self.assertEqual(settings.name, "from-kwargs")
        self.assertEqual(settings.effective_provider, "mock")

    def test_unknown_provider_fails_even_when_disabled(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled), self.assertRaises(ValidationError):
                ModelSettings(provider="unknown", enabled=enabled)
            with self.subTest(runtime_enabled=enabled), self.assertRaises(ValidationError):
                RuntimeSettings(model_provider="unknown", llm_enabled=enabled).validate()
        with patch.dict(os.environ, {"MODEL_PROVIDER": "unknown"}, clear=True):
            with self.assertRaises(ValidationError):
                RuntimeSettings.from_environment()

    def test_unused_provider_configuration_can_be_empty_or_zero(self):
        for values in ({"enabled": False}, {"provider": "disabled"}, {"provider": "mock"}):
            with self.subTest(values=values):
                settings = ModelSettings(
                    **values, name="", base_url="", timeout_seconds=0, max_tokens=0, required=True,
                )
                self.assertNotEqual(settings.effective_provider, "qwen")
                self.assertTrue(settings.required)

    def test_qwen_requires_name_url_and_positive_request_limits(self):
        for values in (
            {"name": " \t"}, {"base_url": ""}, {"timeout_seconds": 0},
            {"timeout_seconds": -1}, {"max_tokens": 0}, {"max_tokens": -1},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ModelSettings(**values)

    def test_direct_field_values_keep_strict_types(self):
        invalid = (
            {"enabled": 0}, {"enabled": "false"}, {"required": 1},
            {"enable_thinking": None}, {"max_tokens": True}, {"max_tokens": 1.0},
            {"max_tokens": "1"}, {"timeout_seconds": True}, {"timeout_seconds": "1"},
            {"name": 1}, {"base_url": None}, {"api_key": 1},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ModelSettings(provider="disabled", **values)
        for field_name in ("llm_enabled", "llm_required", "llm_enable_thinking"):
            with self.subTest(field_name=field_name), self.assertRaises(ValidationError):
                RuntimeSettings(**{field_name: 1}).validate()

    def test_invalid_environment_scalars_fail_without_coercing_numbers(self):
        for name, values in {
            "LLM_ENABLED": ("invalid", "2", "none"),
            "LLM_REQUIRED": ("2",), "LLM_ENABLE_THINKING": ("2",),
            "LLM_MAX_TOKENS": ("true", "1.0", "1.5"),
            "LLM_TIMEOUT_SECONDS": ("true", "invalid"),
        }.items():
            for value in values:
                with self.subTest(name=name, value=value), patch.dict(os.environ, {
                    "MODEL_PROVIDER": "disabled", name: value,
                }, clear=True), self.assertRaises(ValidationError):
                    RuntimeSettings.from_environment()

    def test_nonfinite_timeout_fails_for_every_provider(self):
        for provider in ("qwen", "mock", "disabled"):
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(provider=provider, value=value), self.assertRaises(ValidationError):
                    ModelSettings(provider=provider, timeout_seconds=value)
            with patch.dict(os.environ, {
                "MODEL_PROVIDER": provider, "LLM_TIMEOUT_SECONDS": "NaN",
            }, clear=True), self.assertRaises(ValidationError):
                RuntimeSettings.from_environment()

    def test_api_key_is_hidden_in_representations_and_validation_messages(self):
        secret = "sk-private-value-for-test"
        settings = ModelSettings(api_key=secret)
        runtime = RuntimeSettings(llm_api_key=secret)
        self.assertEqual(settings.api_key, secret)
        self.assertEqual(runtime.model_settings.api_key, secret)
        self.assertNotIn(secret, repr(settings))
        self.assertNotIn(secret, str(settings))
        self.assertNotIn(secret, repr(runtime))
        with self.assertRaises(ValidationError) as caught:
            ModelSettings(api_key=secret, name="")
        self.assertNotIn(secret, str(caught.exception))

    def test_dotenv_does_not_override_process_environment(self):
        self._dotenv.stop()
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_text(
                'MODEL_NAME="from-file" # local name\nMODEL_PROVIDER=mock\nLLM_ENABLED=false\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"MODEL_NAME": "from-process"}, clear=True):
                config_module._load_dotenv(env_file)
                with patch("app.config._load_dotenv"):
                    settings = RuntimeSettings.from_environment().model_settings
        self.assertEqual(settings.name, "from-process")
        self.assertEqual(settings.provider, "mock")
        self.assertEqual(settings.effective_provider, "disabled")


if __name__ == "__main__":
    unittest.main()
