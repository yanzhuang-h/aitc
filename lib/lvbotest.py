"""Compatibility alias for :mod:`lib.green_wave_coordination`.

Keep one module instance so legacy patches and coordination state remain shared.
"""

import sys as _sys

from . import green_wave_coordination as _implementation

_sys.modules[__name__] = _implementation
