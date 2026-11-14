"""Compatibility alias for :mod:`lib.cycle_experience_timing`.

Keep one module instance so legacy patches and coordination state remain shared.
"""

import sys as _sys

from . import cycle_experience_timing as _implementation

_sys.modules[__name__] = _implementation
