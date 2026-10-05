import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.config import ExperienceReleaseSettings, RuntimeSettings
from runtime.application import create_application


class ExperienceReleaseSettingsTests(unittest.TestCase):
    def test_default_manifest_is_in_project_experience_versions(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = ExperienceReleaseSettings()
        expected = Path(__file__).resolve().parents[1] / "lib" / "experience_versions"
        self.assertEqual(settings.versions_dir, expected)
        self.assertEqual(settings.active_manifest_path, expected / "active_manifest.json")

    def test_versions_override_and_explicit_manifest_use_existing_environment_names(self):
        with tempfile.TemporaryDirectory() as directory:
            versions = Path(directory) / "versions"
            explicit = Path(directory) / "explicit.json"
            with mock.patch.dict(os.environ, {"AITC_EXPERIENCE_VERSIONS_DIR": str(versions)}, clear=True):
                self.assertEqual(ExperienceReleaseSettings().active_manifest_path, versions / "active_manifest.json")
                with mock.patch.dict(os.environ, {"AITC_EXPERIENCE_MANIFEST": str(explicit)}):
                    self.assertEqual(ExperienceReleaseSettings().active_manifest_path, explicit)

    def test_explicit_application_settings_are_shared_by_writer_and_scheduler(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = ExperienceReleaseSettings(manifest=root / "explicit.json")
            settings = RuntimeSettings(
                runtime_data_dir=root / "runtime", runtime_output_dir=root / "logs",
                prediction_data_dir=root / "predictions", llm_enabled=False,
                enable_prediction_scheduler=False, experience_release=release,
            )
            with mock.patch.dict(os.environ, {"AITC_EXPERIENCE_MANIFEST": str(root / "other.json")}):
                app = create_application(settings=settings)
            self.assertEqual(app.decision_pipeline.writer.experience_manifest_path, release.active_manifest_path)
            self.assertIs(app.experience_pool_scheduler.release_settings, release)
            scheduler = app.experience_pool_scheduler
            with mock.patch(
                "lib.data_ANS.experience_runtime.run_experience_pool_day",
                return_value={"status": "completed"},
            ) as run_day:
                scheduler.run_for_date(source_date="2026-07-17")
            run_day.assert_called_once_with(dt.date(2026, 7, 17), release_settings=release)
