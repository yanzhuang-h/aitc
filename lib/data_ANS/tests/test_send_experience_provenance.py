import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from infra.data.output_store import FileRuntimeOutputStore
from infra.data.result_sender import ResultSender
from infra.data.writer import RuntimeDataWriter


class _Client:
    def __init__(self):
        self.frames = []

    def sendall(self, frame):
        self.frames.append(frame)


class SendExperienceProvenanceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manifest = self.root / "active_manifest.json"
        self.writer = RuntimeDataWriter(
            FileRuntimeOutputStore(self.root / "logs"),
            experience_manifest_path=self.manifest,
        )
        self.revision = 0
        self.provenance = {"release_id": "experience_v1", "active_sha256": "abc123"}

    def _write_manifest(self, content):
        self.manifest.write_text(content, encoding="utf-8")
        self.revision += 1
        timestamp = 1_700_000_000_000_000_000 + self.revision * 1_000_000
        os.utime(self.manifest, ns=(timestamp, timestamp))

    def _send_logs(self):
        path = next((self.root / "logs" / "send").glob("*.txt"))
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_reads_active_release_manifest_for_local_send_log(self):
        self._write_manifest(json.dumps({**self.provenance, "schema_version": 1}))
        result = {"CrossId": "1300069", "action": [10, 20], "nested": {"value": 1}}
        original = copy.deepcopy(result)
        clients = [_Client(), _Client()]

        disconnected = ResultSender(writer=self.writer).send_batch(clients, [result])

        self.assertEqual(disconnected, [])
        self.assertEqual(result, original)
        for client in clients:
            self.assertEqual(client.frames, [(json.dumps(original) + "\n").encode("utf-8")])
        logs = self._send_logs()
        self.assertEqual(len(logs), 2)
        for log in logs:
            self.assertEqual(log.pop("AITC_EXPERIENCE_PROVENANCE"), self.provenance)
            self.assertIsInstance(log.pop("AITC_SYS_TS"), int)
            self.assertEqual(log, original)

    def test_missing_manifest_keeps_sending_without_provenance(self):
        client = _Client()
        result = {"CrossId": "1300069"}

        self.assertEqual(ResultSender(writer=self.writer).send_batch([client], [result]), [])

        self.assertEqual(json.loads(client.frames[0]), result)
        self.assertNotIn("AITC_EXPERIENCE_PROVENANCE", self._send_logs()[0])

    def test_valid_manifest_is_cached_and_returned_as_a_copy(self):
        self._write_manifest(json.dumps(self.provenance))
        with mock.patch("infra.data.writer.json.load", wraps=json.load) as load:
            first = self.writer.get_active_experience_provenance()
            first["release_id"] = "caller_changed_it"
            second = self.writer.get_active_experience_provenance()

        self.assertEqual(second, self.provenance)
        load.assert_called_once()

    def test_refreshes_after_manifest_changes_deletion_and_recreation(self):
        self._write_manifest(json.dumps(self.provenance))
        self.assertEqual(self.writer.get_active_experience_provenance(), self.provenance)
        updated = {"release_id": "experience_v2", "active_sha256": "def456"}
        self._write_manifest(json.dumps(updated))
        self.assertEqual(self.writer.get_active_experience_provenance(), updated)
        self.manifest.unlink()
        self.writer.write_send_result({"CrossId": "1300069"})
        self.assertNotIn("AITC_EXPERIENCE_PROVENANCE", self._send_logs()[0])
        self._write_manifest(json.dumps(self.provenance))
        self.assertEqual(self.writer.get_active_experience_provenance(), self.provenance)

    def test_atomic_replacement_with_unchanged_mtime_and_size_refreshes_cache(self):
        self._write_manifest(json.dumps(self.provenance))
        self.assertEqual(self.writer.get_active_experience_provenance(), self.provenance)
        original_stat = self.manifest.stat()
        updated = {"release_id": "experience_v2", "active_sha256": "def456"}
        replacement = self.root / "replacement.json"
        replacement.write_text(json.dumps(updated), encoding="utf-8")
        os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        replacement.replace(self.manifest)
        replaced_stat = self.manifest.stat()
        self.assertEqual(replaced_stat.st_mtime_ns, original_stat.st_mtime_ns)
        self.assertEqual(replaced_stat.st_size, original_stat.st_size)
        self.assertNotEqual(replaced_stat.st_ino, original_stat.st_ino)

        self.assertEqual(self.writer.get_active_experience_provenance(), updated)

    def test_invalid_manifest_drops_old_provenance_without_blocking_send(self):
        for content in (
            "not-json", "[]", '"text"',
            '{"release_id": "missing-hash"}',
            '{"release_id": 123, "active_sha256": "abc123"}',
            '{"release_id": "experience_v1", "active_sha256": null}',
            '{"release_id": "", "active_sha256": "abc123"}',
            '{"release_id": "experience_v1", "active_sha256": ""}',
        ):
            with self.subTest(content=content):
                self._write_manifest(json.dumps(self.provenance))
                self.assertEqual(self.writer.get_active_experience_provenance(), self.provenance)
                self._write_manifest(content)
                client = _Client()
                with self.assertLogs("infra.data.writer", level="WARNING"):
                    disconnected = ResultSender(writer=self.writer).send_batch(
                        [client], [{"CrossId": "1300069"}],
                    )
                self.assertEqual(disconnected, [])
                self.assertEqual(json.loads(client.frames[0]), {"CrossId": "1300069"})
                self.assertNotIn("AITC_EXPERIENCE_PROVENANCE", self._send_logs()[-1])

    def test_io_failures_clear_cached_provenance_and_allow_recovery(self):
        for operation in ("stat", "open"):
            with self.subTest(operation=operation):
                self._write_manifest(json.dumps(self.provenance))
                self.assertEqual(self.writer.get_active_experience_provenance(), self.provenance)
                self._write_manifest(json.dumps(self.provenance))
                with mock.patch.object(Path, operation, side_effect=PermissionError("unreadable")):
                    with self.assertLogs("infra.data.writer", level="WARNING"):
                        self.assertEqual(self.writer.get_active_experience_provenance(), {})
                self.assertEqual(self.writer.get_active_experience_provenance(), self.provenance)

    def test_output_write_failure_is_still_reported(self):
        with mock.patch.object(self.writer.store, "write", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.writer.write_send_result({"CrossId": "1300069"})


if __name__ == "__main__":
    unittest.main()
