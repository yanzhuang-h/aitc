import ast
from contextlib import redirect_stderr
from io import StringIO
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "onboard_intersection.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("onboard_intersection", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literal_of(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                value = node.value
                if isinstance(value, ast.Call):
                    if isinstance(value.func, ast.Attribute):
                        value = value.func.value
                    elif isinstance(value.func, ast.Name) and value.args:
                        inner = value.args[0]
                        if isinstance(inner, (ast.Set, ast.List, ast.Tuple, ast.Dict)):
                            value = inner
                return ast.literal_eval(value)
    raise AssertionError(f"{name} not found in {path}")


class OnboardIntersectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "lib").mkdir()
        shutil.copy(ROOT / "Lambdas.py", self.root / "Lambdas.py")
        self.cross_info = self.root / "lib" / "cross_info.json"
        self.cross_info.write_text(json.dumps({"999999": {
            "jtll_ddbh": {"100009": "U", "100010": "D"},
            "phase": {"1": "UD"},
            "LaneNo": {"U": {"1": "1B"}, "D": {"1": "1B"}},
            "Cycle": [[1]],
        }}), encoding="utf-8")
        self.road_info = self.root / "lib" / "road_info.json"
        self.program = {"phase": ["UD"], "min_pass_time": [15], "max_pass_time": [90]}
        self.road_info.write_text(json.dumps({"999999": {"1": self.program, "3": self.program}}),
                                  encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)
        self.tool = _load_tool()

    def _apply(self, *args):
        return self.tool.main([
            "--root", str(self.root),
            "--cross-info", str(self.cross_info),
            "--cross", "999999",
            "--apply",
            *args,
        ])

    def test_onboard_writes_one_registry_and_runtime_derives_all_mappings(self):
        existing = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(self._apply(), 0)
        self.assertEqual(existing, {path: path.read_bytes() for path in existing})
        registry = self.root / "lib" / "plan_id_overrides.json"
        self.assertEqual(json.loads(registry.read_text()), {"999999": {"program_id": 1}})

        probe = """
from pathlib import Path
import sys
from unittest.mock import patch
from app import paths
from lib import cross_info_functions, intersection_strategy
from lib._local_json_store import read_json_object
from lib.platform_registration import registered_platform_programs

directory = Path(sys.argv[1])
registry = directory / "plan_id_overrides.json"
programs = registered_platform_programs(read_json_object(registry))
programs["888888"] = 1
with patch.object(paths, "ROAD_INFO_PATH", directory / "road_info.json"), \\
        patch.object(cross_info_functions, "CROSS_INFO_PATH", directory / "cross_info.json"), \\
        patch.object(intersection_strategy, "_PLAN_OVERRIDES_PATH", registry), \\
        patch.object(intersection_strategy, "PLATFORM_ROAD_PROGRAMS", programs), \\
        patch.object(intersection_strategy, "PLATFORM_PHASE_ROAD_IDS", frozenset(programs)):
    import Lambdas
    from lib import DQN_Select, Global_intersection_coordinate
    from lib.data_ANS import flow_allocator_shadow as shadow, experience_runtime as runtime
    assert "999999" in Lambdas.intersection_list and "888888" not in Lambdas.intersection_list
    assert all("999999" in values for values in Lambdas.config_lambda.values())
    assert Lambdas.location_to_intersection_lambda[100009] == ("999999", "U")
    assert "999999" in Lambdas.map_lambda and "999999" in Lambdas.max_lengths_lambda
    assert "999999" in DQN_Select.Cross_Video and "888888" not in DQN_Select.Cross_Video
    assert 999999 in Global_intersection_coordinate.video_flow_road
    assert 888888 not in Global_intersection_coordinate.video_flow_road
    assert intersection_strategy.program_id_override("999999") == 1
    with patch.dict("os.environ", {}, clear=True):
        assert "999999" in shadow._target_road_ids()
        assert "999999" in runtime._configured_collection_roads()
        assert "999999" in runtime._configured_update_roads()
"""
        subprocess.run([sys.executable, "-c", probe, str(self.root / "lib")], cwd=ROOT, check=True, timeout=30)

    def test_onboard_is_idempotent(self):
        self._apply()
        registry = self.root / "lib" / "plan_id_overrides.json"
        first = registry.stat().st_mtime_ns
        self._apply()
        self.assertEqual(first, registry.stat().st_mtime_ns)

    def test_invalid_config_fails_before_writing_any_registrations(self):
        cases = [
            ({}, (), "road_info.json"),
            ({"999999": {"1": dict(self.program, min_pass_time=[95])}}, (), "conflicting phase bounds"),
            ({"999999": {"1": self.program}}, ("--program-id", "2"), "默认方案 2"),
        ]
        for programs, flags, message in cases:
            self.road_info.write_text(json.dumps(programs), encoding="utf-8")
            before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
            with self.subTest(message=message), redirect_stderr(StringIO()) as stderr:
                with self.assertRaises(SystemExit) as failure:
                    self._apply(*flags)
            self.assertEqual(failure.exception.code, 2)
            self.assertIn(message, stderr.getvalue())
            self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_rejects_cycle_with_undefined_stage(self):
        crosses = json.loads(self.cross_info.read_text(encoding="utf-8"))
        crosses["999999"]["Cycle"] = [[1, 2]]
        self.cross_info.write_text(json.dumps(crosses), encoding="utf-8")
        before = (self.root / "Lambdas.py").read_bytes()
        with redirect_stderr(StringIO()) as stderr, self.assertRaises(SystemExit) as failure:
            self._apply()
        self.assertEqual(failure.exception.code, 2)
        self.assertIn("未定义的阶段", stderr.getvalue())
        self.assertEqual((self.root / "Lambdas.py").read_bytes(), before)

    def test_rejects_conflicting_detector_before_writes(self):
        mapping = _literal_of(self.root / "Lambdas.py", "location_to_intersection_lambda")
        detector = next(iter(mapping))
        cross_data = json.loads(self.cross_info.read_text(encoding="utf-8"))
        cross_data["999999"]["jtll_ddbh"] = {str(detector): "U"}
        self.cross_info.write_text(json.dumps(cross_data), encoding="utf-8")
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with redirect_stderr(StringIO()) as stderr, self.assertRaises(SystemExit) as failure:
            self._apply()
        self.assertEqual(failure.exception.code, 2)
        self.assertIn(f"检测器 {detector}", stderr.getvalue())
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_reapply_preserves_the_selected_existing_default(self):
        self.assertEqual(self._apply("--program-id", "3"), 0)
        self.assertEqual(self._apply(), 0)
        overrides = json.loads((self.root / "lib" / "plan_id_overrides.json").read_text(encoding="utf-8"))
        self.assertEqual(overrides["999999"], {"program_id": 3})

    def test_reapply_keeps_platform_registration_for_existing_road(self):
        (self.root / "Lambdas.py").write_text(
            'intersection_list = ["999999"]\n'
            'location_to_intersection_lambda = {100009: ("999999", "U"), 100010: ("999999", "D")}\n'
            'aibi_to_xinkongji = {}\n',
            encoding="utf-8",
        )
        registry = self.root / "lib" / "plan_id_overrides.json"
        registry.write_text('{"999999": {"program_id": 1}}', encoding="utf-8")
        self.assertEqual(self._apply("--program-id", "3"), 0)
        self.assertEqual(json.loads(registry.read_text(encoding="utf-8")), {"999999": {"program_id": 3}})


if __name__ == "__main__":
    unittest.main()
