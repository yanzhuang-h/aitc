"""安全引擎抽象：最终安全校验。"""

from __future__ import annotations

from typing import Any, Protocol


class SafetyEngine(Protocol):
    """安全引擎抽象。

    对单点或协同后的方案做最终安全校验：绿灯上下限、行人最小绿、
    相位冲突、周期一致性、下游溢出风险等。
    """

    def check(self, plans: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """校验一组路口方案，返回校验结果（安全/问题列表/修正建议）。"""
