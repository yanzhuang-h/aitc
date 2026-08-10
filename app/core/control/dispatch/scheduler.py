"""全局路口调度判断：决定每个路口的控制路径。

多数路口走完单点即可直接下发；只有部分路口需要进入多路口协同
（绿波成组 / 应急管理）。本模块负责这个"走哪条路"的判断。
"""

from __future__ import annotations

import logging
from typing import Any


class SynergyScheduler:
    """多路口协同调度判断。"""

    def __init__(
        self,
        green_wave_controller: Any | None = None,
        emergency_controller: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.green_wave = green_wave_controller
        self.emergency = emergency_controller
        self.logger = logger or logging.getLogger("aitc.control.scheduler")

    def decide(
        self,
        cross_ids: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """为一批路口做调度决策。

        返回:
            {
              "direct": [走单点直发的路口],
              "green_wave": [[成组走绿波的路口], ...],
              "emergency": [走应急控制的路口],
            }

        骨架实现：默认全部直发，绿波/应急条件接入后按需分流。
        """
        emergency_ids: list[str] = []
        if self.emergency is not None:
            emergency_ids = self.emergency.detect(context)

        green_wave_groups: list[list[str]] = []
        if self.green_wave is not None and self.green_wave.should_apply(cross_ids, context):
            green_wave_groups.append(list(cross_ids))

        emergency_set = set(emergency_ids)
        green_wave_set = {c for group in green_wave_groups for c in group}
        direct = [c for c in cross_ids if c not in emergency_set and c not in green_wave_set]
        return {
            "direct": direct,
            "green_wave": green_wave_groups,
            "emergency": emergency_ids,
        }
