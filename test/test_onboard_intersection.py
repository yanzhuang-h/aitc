import ast
from contextlib import redirect_stderr
from io import StringIO
import importlib.util
import json
import shutil
import tempfile
import unittest
from unittest import mock
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


SOURCE_FILES = (
    "Lambdas.py",
    "lib/DQN_Select.py",
    "lib/intersection_strategy.py",
    "lib/Global_intersection_coordinate.py",
    "lib/data_ANS/flow_allocator_shadow.py",
    "lib/data_ANS/experience_runtime.py",
)
SOURCE_AVAILABLE = all((ROOT / name).is_file() for name in SOURCE_FILES)


@unittest.skipUnless(
    SOURCE_AVAILABLE,
    "源码已被 Cython 编译为 .so（发布包回归阶段跳过本测试）",
)
class OnboardIntersectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "lib" / "data_ANS").mkdir(parents=True)
        shutil.copy(ROOT / "Lambdas.py", self.root / "Lambdas.py")
        shutil.copy(ROOT / "lib" / "DQN_Select.py", self.root / "lib" / "DQN_Select.py")
        shutil.copy(ROOT / "lib" / "intersection_strategy.py", self.root / "lib" / "intersection_strategy.py")
        shutil.copy(
            ROOT / "lib" / "Global_intersection_coordinate.py",
            self.root / "lib" / "Global_intersection_coordinate.py",
        )
        shutil.copy(
            ROOT / "lib" / "data_ANS" / "flow_allocator_shadow.py",
            self.root / "lib" / "data_ANS" / "flow_allocator_shadow.py",
        )
        shutil.copy(
            ROOT / "lib" / "data_ANS" / "experience_runtime.py",
            self.root / "lib" / "data_ANS" / "experience_runtime.py",
        )
        self.cross_info = self.root / "cross_info.json"
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

    def test_onboard_adds_all_registries(self):
        self._apply()

        config_lambda = _literal_of(self.root / "Lambdas.py", "config_lambda")
        for key, values in config_lambda.items():
            self.assertIn("999999", {str(item) for item in values}, key)
            self.assertEqual(list(map(str, values)).count("999999"), 1, key)

        intersections = _literal_of(self.root / "Lambdas.py", "intersection_list")
        self.assertIn("999999", {str(item) for item in intersections})

        locations = _literal_of(
            self.root / "Lambdas.py", "location_to_intersection_lambda"
        )
        self.assertEqual(locations[100009], ("999999", "U"))

        cross_video = _literal_of(self.root / "lib" / "DQN_Select.py", "Cross_Video")
        self.assertIn("999999", cross_video)

        video_flow = _literal_of(
            self.root / "lib" / "Global_intersection_coordinate.py", "video_flow_road"
        )
        self.assertIn(999999, video_flow)

        strategy = _literal_of(self.root / "lib/intersection_strategy.py", "PLATFORM_PHASE_ROAD_IDS")
        self.assertIn("999999", strategy)
        from lib.data_ANS import flow_allocator_shadow as shadow
        from lib.data_ANS import experience_runtime as runtime
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(shadow, "PLATFORM_PHASE_ROAD_IDS", strategy), \
                mock.patch.object(runtime, "PLATFORM_PHASE_ROAD_IDS", strategy):
            self.assertIn("999999", shadow._target_road_ids())
            self.assertIn("999999", runtime._configured_collection_roads())
            self.assertIn("999999", runtime._configured_update_roads())
        dqn_text = (self.root / "lib" / "DQN_Select.py").read_text(encoding="utf-8-sig")
        self.assertNotIn("def DQN_select_999999(", dqn_text)
        self.assertNotIn("cross_id == '999999'", dqn_text)
        self.assertIn("return DQN_select_online(", dqn_text)

        overrides = json.loads(
            (self.root / "lib" / "plan_id_overrides.json").read_text(encoding="utf-8")
        )
        self.assertEqual(overrides["999999"], 1)

    def test_onboard_is_idempotent(self):
        self._apply()
        first = (self.root / "Lambdas.py").read_text(encoding="utf-8-sig")
        self._apply()
        second = (self.root / "Lambdas.py").read_text(encoding="utf-8-sig")
        self.assertEqual(first, second)


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
        self.assertEqual(overrides["999999"], 3)


if __name__ == "__main__":
    unittest.main()
