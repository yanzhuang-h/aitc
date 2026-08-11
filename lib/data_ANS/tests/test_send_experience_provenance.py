import json
import tempfile
import unittest
from pathlib import Path

import Write_to_file as WRITER


class SendExperienceProvenanceTests(unittest.TestCase):
    def test_reads_active_release_manifest_for_local_send_log(self):
        original_path = WRITER.EXPERIENCE_MANIFEST_PATH
        original_cache = dict(WRITER.experience_manifest_cache)
        try:
            with tempfile.TemporaryDirectory() as directory:
                manifest_path = Path(directory) / "active_manifest.json"
                manifest_path.write_text(json.dumps({
                    "release_id": "experience_test",
                    "active_sha256": "abc123",
                }), encoding="utf-8")
                WRITER.EXPERIENCE_MANIFEST_PATH = str(manifest_path)
                WRITER.experience_manifest_cache = {
                    "mtime_ns": None,
                    "value": {},
                }

                provenance = WRITER.get_active_experience_provenance()

                self.assertEqual(provenance["release_id"], "experience_test")
                self.assertEqual(provenance["active_sha256"], "abc123")
        finally:
            WRITER.EXPERIENCE_MANIFEST_PATH = original_path
            WRITER.experience_manifest_cache = original_cache


if __name__ == "__main__":
    unittest.main()
