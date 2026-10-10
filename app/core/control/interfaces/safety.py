"""安全引擎抽象：最终安全校验。"""

from __future__ import annotations

from typing import Any, Protocol
from app.core.control.safety_schemas import PlanSafetyResult


class SafetyEngine(Protocol):
    """安全引擎抽象。

    仅声明实际实现的结构与静态上下界检查，不承诺缺失的交通业务规则。
    """

    def check(self, intersection_id: str, raw_plan: Any, *, config: dict | None = None) -> PlanSafetyResult:
        """返回严格检查结果；覆盖不完整显式标记 partial。"""
