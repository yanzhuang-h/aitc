"""路口方案生成：由路口状态生成单点控制方案。

当前实现先包装现有 DQN 算法（lib.DQN_Select），保持单点控制完备性；
后续可替换为多输入融合算法，接口保持不变。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.tools.signal_timing import SingleIntersectionSignalTimingTool


class SinglePointPlanGenerator:
    """单点路口方案生成，实现 SinglePointPlanner 接口。"""

    def __init__(
        self,
        signal_timing_tool: SingleIntersectionSignalTimingTool | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.signal_timing_tool = signal_timing_tool or SingleIntersectionSignalTimingTool()
        self.logger = logger or logging.getLogger("aitc.control.single_point")

    def generate(self, cross_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
        """根据路口状态生成单点控制方案。

        参数:
            cross_id: 路口编号。
            state: 路口详细状态（可由 IntersectionDetailState 生成），
                可为 None，此时使用工具默认输入做冒烟验证。
        """
        state = state or {}
        traffic_vector = state.get("traffic_vector")
        kwargs: dict[str, Any] = {}
        if traffic_vector is not None:
            kwargs["traffic_vector"] = traffic_vector
        result = self.signal_timing_tool.generate(cross_id=cross_id, **kwargs)
        return {
            "cross_id": str(cross_id),
            "plan": result,
            "source": "dqn",
        }
