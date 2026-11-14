"""Old imports must share timing functions and mutable state with renamed modules."""

import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PAIRS = (
    ("lib.cha", "lib.cycle_experience_timing"),
    ("lib.cha1", "lib.movement_experience_timing"),
    ("lib.lvbotest", "lib.green_wave_coordination"),
)


class ModuleNameCompatibilityTests(unittest.TestCase):
    def test_both_import_orders_share_a_single_module(self):
        # Fresh processes catch order-dependent duplicate module initialization.
        script = """
import importlib
import sys
old, new, legacy_first = sys.argv[1:]
first, second = (old, new) if legacy_first == 'yes' else (new, old)
a = importlib.import_module(first)
b = importlib.import_module(second)
assert a is b, (first, second)
package = importlib.import_module('lib')
assert getattr(package, old.rsplit('.', 1)[1]) is b
assert getattr(package, new.rsplit('.', 1)[1]) is b
probe = object()
a._compatibility_probe = probe
assert b._compatibility_probe is probe
"""
        for old, new in MODULE_PAIRS:
            for legacy_first in ("yes", "no"):
                with self.subTest(module=old, legacy_first=legacy_first):
                    result = subprocess.run(
                        [sys.executable, "-c", script, old, new, legacy_first],
                        cwd=Path(__file__).resolve().parents[1],
                        capture_output=True, text=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_patch_controls_new_timing_function(self):
        legacy = importlib.import_module("lib.cha1")
        current = importlib.import_module("lib.movement_experience_timing")
        with patch.object(legacy, "jiangyan_biao_get", return_value={"U": {}}), \
             patch("builtins.print"):
            self.assertEqual(current.chuli_shuju3("9900001", {}), [0] * 10)

    def test_green_wave_service_observes_legacy_state(self):
        from control.synergy.green_wave_service import GreenWaveDataService

        legacy = importlib.import_module("lib.lvbotest")
        current = importlib.import_module("lib.green_wave_coordination")
        # The private corridor state must not split from the state used by legacy callers.
        with patch.object(legacy, "cnt", 17), \
             patch.object(legacy, "_ACTIVE_CORRIDOR_ID", "compat-corridor"):
            state = current._capture_active_state()
            self.assertEqual(state["cnt"], 17)
            self.assertEqual(current._ACTIVE_CORRIDOR_ID, "compat-corridor")
            status = GreenWaveDataService().status()
            self.assertEqual(status["round"], 17)
            self.assertEqual(status["corridor_id"], "compat-corridor")


if __name__ == "__main__":
    unittest.main()
