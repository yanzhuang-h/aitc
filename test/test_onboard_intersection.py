import ast
import importlib.util
import json
import shutil
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


SOURCE_FILES = (
    "Lambdas.py",
    "lib/DQN_Select.py",
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
        self.cross_info.write_text(
            json.dumps({"999999": {"jtll_ddbh": {"100009": "U", "100010": "D"}}}),
            encoding="utf-8",
        )
        self.addCleanup(self.tmp.cleanup)
        self.tool = _load_tool()

    def _apply(self):
        self.tool.main([
            "--root", str(self.root),
            "--cross-info", str(self.cross_info),
            "--cross", "999999",
            "--apply",
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

        pilot_roads = _literal_of(
            self.root / "lib" / "data_ANS" / "flow_allocator_shadow.py",
            "DEFAULT_TARGET_ROAD_IDS",
        )
        self.assertIn("999999", {str(item) for item in pilot_roads})

        collection = _literal_of(
            self.root / "lib" / "data_ANS" / "experience_runtime.py",
            "DEFAULT_POOL_COLLECTION_ROAD_IDS",
        )
        update = _literal_of(
            self.root / "lib" / "data_ANS" / "experience_runtime.py",
            "DEFAULT_TABLE_UPDATE_ROAD_IDS",
        )
        self.assertIn("999999", {str(item) for item in collection})
        self.assertIn("999999", {str(item) for item in update})

        dqn_text = (self.root / "lib" / "DQN_Select.py").read_text(encoding="utf-8-sig")
        self.assertIn("def DQN_select_999999(", dqn_text)
        self.assertIn("cross_id == '999999'", dqn_text)
        function_body = dqn_text.split("def DQN_select_999999(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("select_pilot_schedule", function_body)

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


if __name__ == "__main__":
    unittest.main()
