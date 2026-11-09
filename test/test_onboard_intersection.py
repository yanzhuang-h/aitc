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
                if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                    value = value.func.value
                return ast.literal_eval(value)
    raise AssertionError(f"{name} not found in {path}")


class OnboardIntersectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "lib").mkdir()
        shutil.copy(ROOT / "Lambdas.py", self.root / "Lambdas.py")
        shutil.copy(ROOT / "lib" / "DQN_Select.py", self.root / "lib" / "DQN_Select.py")
        shutil.copy(
            ROOT / "lib" / "Global_intersection_coordinate.py",
            self.root / "lib" / "Global_intersection_coordinate.py",
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
            self.assertEqual(
                list(map(str, values)).count("999999"), 1, key
            )

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

        dqn_text = (self.root / "lib" / "DQN_Select.py").read_text(encoding="utf-8-sig")
        self.assertIn("def DQN_select_999999(", dqn_text)
        self.assertIn("cross_id == '999999'", dqn_text)

    def test_onboard_is_idempotent(self):
        self._apply()
        first = (self.root / "Lambdas.py").read_text(encoding="utf-8-sig")
        self._apply()
        second = (self.root / "Lambdas.py").read_text(encoding="utf-8-sig")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
