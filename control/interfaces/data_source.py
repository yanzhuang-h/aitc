"""数据输入抽象：控制模块所需的融合后路口状态与协同上下文。"""

from __future__ import annotations

from typing import Any, Protocol


class DataSource(Protocol):
    """控制模块的数据来源抽象。

    输入来自数据底座：本地感知（车辆/排队/相位）、互联网融合数据、
    视频感知补充、路口状态与配置。返回结构统一为路口级字典。
    """

    def get_intersection_state(self, cross_id: str) -> dict[str, Any]:
        """获取单个路口的融合后状态（流量/排队/相位/互联网融合等）。"""

    def get_intersection_context(self, cross_id: str) -> dict[str, Any]:
        """获取单路口控制所需的上下文（约束/配置/经验/上下游关联）。"""

    def get_synergy_context(self, cross_ids: list[str]) -> dict[str, Any]:
        """获取一组路口的协同上下文（成组关系/上下游/溢出风险等）。"""
