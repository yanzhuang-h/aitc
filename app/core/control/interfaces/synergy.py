"""多路口协同控制抽象（绿波 / 应急）。"""

from __future__ import annotations

from typing import Any, Protocol


class SynergyController(Protocol):
    """多路口协同控制抽象。

    只在全局路口调度判断认定需要协同时启用。输入一组路口的单点方案，
    输出协调后的方案（可能对相位/绿灯时长做大幅调整）。
    """

    def should_apply(self, cross_ids: list[str], context: dict[str, Any]) -> bool:
        """判断当前是否满足启用该协同控制的条件。"""

    def apply(self, plans: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """对一组路口的单点方案做协同调整，返回调整后的方案。"""
