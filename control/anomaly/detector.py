"""异常处理模块：路口数据异常状态判断与降级。

当路口输入数据缺失、异常或无法参与正常方案生成时，
进行异常识别并给出降级策略（如使用默认方案、跳过预测等）。
"""

from __future__ import annotations

import logging
from typing import Any


class AnomalyDetector:
    """路口数据异常状态判断。"""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("aitc.control.anomaly")

    def detect(self, state: dict[str, Any]) -> dict[str, Any]:
        """检测路口数据异常，返回异常结论与降级建议。

        返回:
            {
              "abnormal": bool,
              "reasons": [原因列表],
              "fallback": "降级策略（如 default_plan）",
            }

        骨架实现：仅检查是否完全没有运行数据；更细的异常规则后续补充。
        """
        has_data = bool(state.get("flow") or state.get("queue") or state.get("phase"))
        return {
            "abnormal": not has_data,
            "reasons": [] if has_data else ["缺少可用运行数据"],
            "fallback": None if has_data else "default_plan",
        }
