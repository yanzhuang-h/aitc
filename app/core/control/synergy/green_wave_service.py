"""绿波数据查询服务。

参考配置接口的分层方式（lib 函数 -> 服务封装 -> HTTP 路由），
只读封装 lib 层的绿波模块（``lib.lvbotest`` / ``lib.green_wave_functions``），
为 HTTP 协议层和 Agent 提供统一绿波数据查询入口，不修改 lib 实现。
"""

from __future__ import annotations

import logging
from typing import Any

from lib import green_wave_functions, lvbotest


class GreenWaveDataService:
    """绿波数据查询：运行状态、走廊配置、最新下发方案。"""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("aitc.green_wave")

    def status(self) -> dict[str, Any]:
        """绿波协调当前运行状态。"""
        try:
            return {
                "status": "success",
                "running": bool(lvbotest.start),
                "cycle_green": bool(lvbotest.cycle_green),
                "offset_green": bool(lvbotest.offset_green),
                "cycle_done": bool(lvbotest.cycle_done),
                "offset_done": bool(lvbotest.offset_done),
                "round": int(lvbotest.cnt),
                "direction": str(lvbotest.direction),
                "corridor_id": str(getattr(lvbotest, "_ACTIVE_CORRIDOR_ID", "") or ""),
                "last_send_time": int(lvbotest.last_green_wave_send_time or 0),
                "has_fix_plan": lvbotest.fix_plan is not None,
            }
        except Exception as error:
            return self._error(f"读取绿波运行状态失败: {error}")

    def config(self, corridor_id: str | None = None) -> dict[str, Any]:
        """绿波走廊配置：未指定时返回全部走廊，指定时返回单条。"""
        try:
            payload = {"corridor_id": corridor_id} if corridor_id else {}
            if corridor_id:
                return green_wave_functions.get_green_wave_corridor_config(payload)
            return green_wave_functions.list_green_wave_corridors(payload)
        except Exception as error:
            return self._error(f"读取绿波走廊配置失败: {error}")

    def plan(self) -> dict[str, Any]:
        """最新一轮实际下发的绿波方案。"""
        try:
            return {
                "status": "success",
                "corridor_id": str(getattr(lvbotest, "_ACTIVE_CORRIDOR_ID", "") or ""),
                "plan": dict(lvbotest.green_plan_map or {}),
            }
        except Exception as error:
            return self._error(f"读取绿波方案失败: {error}")

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"status": "error", "saved": False, "reason": message}
