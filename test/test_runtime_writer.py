import json
import tempfile
import unittest
from pathlib import Path

from infra.data.classifier import DataKind
from infra.data.output_store import FileRuntimeOutputStore
from infra.data.writer import RuntimeDataWriter


class RuntimeWriterTest(unittest.TestCase):
    def test_writes_compatible_runtime_and_phase_files(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = RuntimeDataWriter(FileRuntimeOutputStore(directory))
            writer.write(DataKind.FLOW, {"value": 1})
            writer.write_phase_check({"status": "ok"})
            flow = next(Path(directory, "flow").glob("*.txt")).read_text(encoding="utf-8")
            phase = next(Path(directory, "phase_check").glob("*.txt")).read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(flow)["value"], 1)
            self.assertIn("AITC_SYS_TS", json.loads(flow))
            self.assertEqual(len(phase), 2)

    def test_writes_experience_file(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = RuntimeDataWriter(FileRuntimeOutputStore(directory))
            writer.write_experience({"reward": 1}, "100")
            path = next(Path(directory, "EXP", "100").glob("*.json"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["EXP"]["reward"], 1)
