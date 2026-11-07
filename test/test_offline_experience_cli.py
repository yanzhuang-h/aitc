import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "tools" / "offline_experience" / "cli.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("offline_experience_cli", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli()


class OfflineExperienceCliTest(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_missing_inputs_return_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, _ = self._run([
                "--dates", "2026-09-01",
                "--roads", "1700542,1700545",
                "--flow-dir", str(root / "flow"),
                "--extend-dir", str(root / "extend"),
                "--cross-info", str(root / "cross_info.json"),
                "--dry-run",
            ])
            plan = json.loads(out)
        self.assertEqual(code, cli.EXIT_NO_DATA)
        self.assertEqual(len(plan["missing_inputs"]), 3)
        self.assertEqual(plan["roads"], ["1700542", "1700545"])

    def test_dry_run_with_complete_inputs_returns_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "flow").mkdir()
            (root / "extend").mkdir()
            (root / "flow" / "2026-09-01_flow.txt").write_text("", encoding="utf-8")
            (root / "extend" / "2026-09-01_extend.txt").write_text("", encoding="utf-8")
            (root / "cross_info.json").write_text("{}", encoding="utf-8")
            code, out, _ = self._run([
                "--dates", "2026-09-01,2026-09-01",
                "--roads", "1700542",
                "--flow-dir", str(root / "flow"),
                "--extend-dir", str(root / "extend"),
                "--cross-info", str(root / "cross_info.json"),
                "--dry-run",
            ])
            plan = json.loads(out)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(plan["missing_inputs"], [])
        self.assertEqual(plan["dates"], ["2026-09-01"])

    def test_invalid_dates_return_usage(self):
        code, _, err = self._run(["--dates", "2026/09/01", "--roads", "1700542", "--dry-run"])
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("参数错误", err)

    def test_invalid_roads_return_usage(self):
        code, _, err = self._run(["--dates", "2026-09-01", "--roads", "abc", "--dry-run"])
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("参数错误", err)

    def test_real_run_reports_not_implemented(self):
        code, _, err = self._run(["--dates", "2026-09-01", "--roads", "1700542"])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("尚未实现", err)


if __name__ == "__main__":
    unittest.main()
