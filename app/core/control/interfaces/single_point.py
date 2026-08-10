"""单点路口方案生成抽象。"""

from __future__ import annotations

from typing import Any, Protocol


class SinglePointPlanner(Protocol):
    """单点路口方案生成抽象。

    输入为融合后的路口状态（含互联网数据、视频感知补充），
    输出为该路口的完整控制方案（相位/绿灯时长等）。
    到这一步，单点控制逻辑已经完备。
    """

    def generate(self, cross_id: str, state: dict[str, Any]) -> dict[str, Any]:
        """根据路口状态生成单点控制方案。"""
