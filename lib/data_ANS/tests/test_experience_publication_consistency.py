from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from lib.data_ANS import experience_release as release
from lib.data_ANS import experience_runtime as runtime
from lib.data_ANS.experience_pool import pool_update_lock


class ExperiencePublicationConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.active = self.root / "active.json"
        self.cross = self.root / "cross.json"
        self.versions = self.root / "versions"
        self.manifest = self.versions / "active_manifest.json"
        self.cross.write_text(json.dumps({
            "1700240": {"LaneNo": {"U": {"1": "1B"}}},
        }))
        self.first = {"1700240": {"U": {"60": [0, 50] + [0] * 8}}}
        self.second = {"1700240": {"U": {"60": [0, 80] + [0] * 8}}}
        self.activate(self.first)

    def activate(self, table):
        return release.activate_validated_experience_table(
            table, str(self.active), str(self.cross), str(self.versions),
            str(self.manifest), require_manifest=True,
        )

    def interrupt_second_publication(self):
        original_write = release._write_json_atomic
        def fail_manifest(path, data):
            if str(path) == str(self.manifest):
                raise OSError("interrupted manifest")
            return original_write(path, data)
        with mock.patch.object(release, "_write_json_atomic", side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, "interrupted"):
                self.activate(self.second)

    def test_manifest_interruption_is_recovered_with_original_rollback_snapshot(self):
        self.interrupt_second_publication()
        self.assertEqual(json.loads(self.active.read_text()), self.second)
        self.assertNotEqual(json.loads(self.manifest.read_text())["active_sha256"],
                            release._canonical_hash(self.second))
        self.assertTrue(Path(str(self.manifest) + ".pending").exists())
        result = self.activate(self.second)
        self.assertTrue(result["unchanged"])
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(manifest["active_sha256"], release._canonical_hash(self.second))
        self.assertEqual(json.loads(Path(manifest["rollback_version_path"]).read_text()), self.first)
        self.assertFalse(Path(str(self.manifest) + ".pending").exists())
        release.rollback_experience_table(str(self.active), str(self.manifest), str(self.cross))
        self.assertEqual(json.loads(self.active.read_text()), self.first)

    def test_release_preview_does_not_repair_or_modify_pending_metadata(self):
        self.interrupt_second_publication()
        pending = Path(str(self.manifest) + ".pending")
        before = (self.active.read_bytes(), self.manifest.read_bytes(), pending.read_bytes())
        candidate, selection, completion = [self.root / name for name in
                                            ["candidate.json", "selection.json", "completion.json"]]
        candidate.write_text(json.dumps(self.second))
        selected = str(self.root / "selected.json")
        selection.write_text(json.dumps({
            "selection": "audit_gated_nearest_rank_percentile_per_lane",
            "policy": {"min_sample_count": 5, "min_date_support": 2},
            "summary": {"accepted_points": 1}, "output_path": selected,
        }))
        completion.write_text(json.dumps({
            "completion_mode": "preserve_trusted_points_interpolation",
            "summary": {"source_points": 1, "completed_points": 1,
                        "changed_source_points": 0, "removed_source_points": 0},
            "input_path": selected, "output_path": str(candidate),
        }))
        result = release.release_experience_table(
            str(candidate), str(selection), str(completion), str(self.active),
            str(self.cross), str(self.versions), str(self.manifest), activate=False,
        )
        self.assertFalse(result["activated"])
        self.assertEqual((self.active.read_bytes(), self.manifest.read_bytes(), pending.read_bytes()), before)

    def test_unproven_legacy_interruption_is_not_acknowledged_as_complete(self):
        self.active.write_text(json.dumps(self.second))
        with self.assertRaisesRegex(release.ExperienceReleaseError, "manifest"):
            self.activate(self.second)
        self.assertEqual(json.loads(self.active.read_text()), self.second)
        self.assertEqual(json.loads(self.manifest.read_text())["active_sha256"],
                         release._canonical_hash(self.first))

    def test_all_public_writers_and_daily_job_share_runtime_table_lock(self):
        for kind in ["activate", "release", "rollback", "daily"]:
            with self.subTest(kind=kind), ThreadPoolExecutor(max_workers=1) as executor:
                started = threading.Event()
                entered = threading.Event()
                def stop_on_entry(*args, **kwargs):
                    entered.set()
                    raise RuntimeError("entered protected body")
                def work():
                    started.set()
                    if kind == "activate":
                        return self.activate(self.second)
                    if kind == "release":
                        return release.release_experience_table(
                            "candidate", "selection", "completion", str(self.active),
                            str(self.cross), str(self.versions),
                        )
                    if kind == "rollback":
                        return release.rollback_experience_table(
                            str(self.active), str(self.manifest), str(self.cross),
                        )
                    return runtime.run_experience_pool_day(dt.date(2026, 11, 12))
                target_module = runtime if kind == "daily" else release
                target_name = "_run_experience_pool_day_unlocked" if kind == "daily" else "_load_json"
                env = {"AITC_EXPERIENCE_POOL_STATE_DIR": str(self.root / "state"),
                       "AITC_EXPERIENCE_RUNTIME_TABLE": str(self.active)}
                with mock.patch.dict(os.environ, env), \
                        mock.patch.object(target_module, target_name, side_effect=stop_on_entry):
                    with pool_update_lock(self.active):
                        future = executor.submit(work)
                        self.assertTrue(started.wait(1))
                        self.assertFalse(entered.wait(0.05))
                    with self.assertRaisesRegex(RuntimeError, "protected body"):
                        future.result(timeout=2)
                self.assertTrue(entered.is_set())

    def test_runtime_file_alias_keeps_shared_target_during_publish_and_rollback(self):
        alias = self.root / "runtime_alias.json"
        alias.symlink_to(self.active)
        release.activate_validated_experience_table(
            self.second, str(alias), str(self.cross), str(self.versions),
            str(self.manifest), require_manifest=True,
        )
        self.assertTrue(alias.is_symlink())
        self.assertEqual(json.loads(self.active.read_text()), self.second)
        release.rollback_experience_table(str(alias), str(self.manifest), str(self.cross))
        self.assertTrue(alias.is_symlink())
        self.assertEqual(json.loads(self.active.read_text()), self.first)

    def test_symlink_alias_is_reentrant_for_same_thread(self):
        real = self.root / "real"
        real.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        code = (
            "from lib.data_ANS.experience_pool import pool_update_lock; "
            "from contextlib import ExitStack; "
            "stack=ExitStack(); "
            f"stack.enter_context(pool_update_lock({str(real / 'table.json')!r})); "
            f"stack.enter_context(pool_update_lock({str(alias / 'table.json')!r})); "
            "stack.close()"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
