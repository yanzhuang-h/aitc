"""路口详细状态生成：把融合数据整理为路口级状态。

输入来自数据底座（本地感知 + 互联网融合 + 视频感知补充），
输出为统一的单点控制输入状态。
"""

from __future__ import annotations

import logging
from typing import Any

from infra.data import MemoryQueryLayer


class IntersectionDetailState:
    """从数据底座生成路口详细状态。"""

    def __init__(
        self,
        query_service: MemoryQueryLayer | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.query_service = query_service
        self.logger = logger or logging.getLogger("aitc.control.detail_state")

    def generate(self, cross_id: str) -> dict[str, Any]:
        """生成路口的详细状态。

        优先从数据底座查询真实运行数据摘要；数据底座不可用时
        返回空状态结构，由上层决定是否使用默认模拟输入。
        """
        state: dict[str, Any] = {
            "cross_id": str(cross_id),
            "flow": [],
            "queue": [],
            "phase": [],
            "internet_fusion": None,  # 互联网数据融合（后续接入）
            "video_supplement": None,  # 视频感知补充（后续接入）
        }
        if self.query_service is not None:
            try:
                state["flow"] = self.query_service.get_runtime_data("flow", limit=20) or []
                state["queue"] = self.query_service.get_runtime_data("queue", limit=20) or []
                state["phase"] = self.query_service.get_runtime_data("stage", limit=20) or []
            except Exception as error:
                self.logger.warning("查询数据底座路口状态失败: %s", error)
        return state
