import json
import tempfile
import unittest
from pathlib import Path

import lib.control_registry as registry_module
from lib.control_registry import (
    ControlRegistryError,
    clear_cache,
    get_registration,
    is_enabled,
    load_registry,
)
from lib.data_ANS.flow_allocator_shadow import DEFAULT_TARGET_ROAD_IDS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "lib" / "control_registry.json"


class ControlRegistryTest(unittest.TestCase):
    def tearDown(self):
        clear_cache()

    def test_default_registry_covers_all_pilot_roads(self):
        registry = load_registry(DEFAULT_REGISTRY, use_cache=False)
        self.assertEqual(set(registry), set(DEFAULT_TARGET_ROAD_IDS))
        self.assertTrue(all(item.enabled for item in registry.values()))

    def test_tongzhou_cameras_are_registered(self):
        registry = load_registry(DEFAULT_REGISTRY, use_cache=False)
        self.assertEqual(
            registry["1700542"].cameras,
            {"R": "110073", "D": "110074", "L": "110075", "U": "110076"},
        )
        self.assertEqual(registry["1700449"].cameras, {"R": "110079", "L": "110080", "U": "110081"})

    def test_unknown_road_returns_none(self):
        self.assertIsNone(get_registration("9999999", DEFAULT_REGISTRY))
        self.assertFalse(is_enabled("9999999", DEFAULT_REGISTRY))

    def test_disabled_and_camera_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "roads": {
                        "1700542": {"enabled": False, "cameras": {"U": "110076"}},
                        "1700545": {"enabled": True, "cameras": {}},
                    },
                }),
                encoding="utf-8",
            )
            registry = load_registry(path, use_cache=False)
            self.assertFalse(registry["1700542"].enabled)
            self.assertTrue(registry["1700545"].enabled)
            self.assertFalse(is_enabled("1700542", path))
            self.assertTrue(is_enabled("1700545", path))

    def test_invalid_direction_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(
                json.dumps({"roads": {"1700542": {"enabled": True, "cameras": {"E": "110073"}}}}),
                encoding="utf-8",
            )
            with self.assertRaises(ControlRegistryError):
                load_registry(path, use_cache=False)

    def test_non_numeric_camera_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(
                json.dumps({"roads": {"1700542": {"enabled": True, "cameras": {"U": "abc"}}}}),
                encoding="utf-8",
            )
            with self.assertRaises(ControlRegistryError):
                load_registry(path, use_cache=False)

    def test_missing_file_is_rejected(self):
        with self.assertRaises(ControlRegistryError):
            load_registry("/tmp/does-not-exist-registry.json", use_cache=False)

    def test_malformed_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ControlRegistryError):
                load_registry(path, use_cache=False)

    def test_cache_returns_copy(self):
        first = load_registry(DEFAULT_REGISTRY)
        first.pop("1700542")
        second = load_registry(DEFAULT_REGISTRY)
        self.assertIn("1700542", second)
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
