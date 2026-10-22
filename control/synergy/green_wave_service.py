"""绿波数据查询服务。

参考配置接口的分层方式（lib 函数 -> 服务封装 -> HTTP 路由），
只读封装 lib 层的绿波模块（``lib.lvbotest`` / ``lib.green_wave_functions``），
为 HTTP 协议层和 Agent 提供统一绿波数据查询入口，不修改 lib 实现。
"""

from __future__ import annotations

import logging
from typing import Any

from lib import green_wave_functions, lvbotest

from .green_wave_api_adapter import (
    adapt_enabled_result,
    adapt_get_result,
    adapt_list_result,
    adapt_save_result,
    doc1_to_corridor,
    is_doc1_payload,
)


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

    # ---- 走廊配置 CRUD（HTTP 层只负责接收，操作全部走 lib 现有函数）----

    def list_corridors(self, full: bool = False) -> dict[str, Any]:
        """走廊列表：full=false 返回摘要（编号/名称/启用），full=true 返回完整配置。"""
        try:
            result = green_wave_functions.list_green_wave_corridors({})
            if full or result.get("status") != "success":
                return adapt_list_result(result)
            result = dict(result)
            result["items"] = [
                {
                    "corridor_id": item.get("corridor_id"),
                    "segment_id": item.get("corridor_id"),
                    "name": item.get("name"),
                    "enabled": item.get("enabled"),
                }
                for item in result.get("items", [])
            ]
            return result
        except Exception as error:
            return self._error(f"读取绿波走廊列表失败: {error}")

    def get_corridor(self, corridor_id: str) -> dict[str, Any]:
        """查询指定走廊完整配置。"""
        try:
            result = green_wave_functions.get_green_wave_corridor_config(
                {"corridor_id": corridor_id}
            )
            return adapt_get_result(result)
        except Exception as error:
            return self._error(f"查询绿波走廊失败: {error}")

    def _resolve_corridor(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """兼容文档1（segment_id/green_wave_info）与文档2（corridor）请求。"""
        if is_doc1_payload(body):
            return doc1_to_corridor(body)
        corridor = body.get("corridor")
        if not isinstance(corridor, dict):
            raise ValueError(
                "请求体需包含 corridor，或使用文档1 的 segment_id/green_wave_info 结构"
            )
        return corridor

    def validate_corridor(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """只校验走廊配置，不保存。支持文档1/文档2 请求，返回文档1 格式。"""
        try:
            corridor = self._resolve_corridor(body)
            result = green_wave_functions.save_green_wave_corridor_config(
                {"dry_run": True, "corridor": corridor}
            )
            return adapt_save_result(
                result, fallback_segment_id=corridor.get("corridor_id", "")
            )
        except Exception as error:
            return self._error(f"校验绿波走廊失败: {error}")

    def update_corridor(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """新增或更新走廊配置并保存。支持文档1/文档2 请求，返回文档1 格式。"""
        try:
            corridor = self._resolve_corridor(body)
            result = green_wave_functions.save_green_wave_corridor_config(
                {"dry_run": False, "corridor": corridor}
            )
            return adapt_save_result(
                result, fallback_segment_id=corridor.get("corridor_id", "")
            )
        except Exception as error:
            return self._error(f"保存绿波走廊失败: {error}")

    def delete_corridor(self, corridor_id: str) -> dict[str, Any]:
        """删除接口：当前无彻底删除函数，转成停用（配置保留，不再参与协调）。"""
        return self.set_corridor_enabled(corridor_id, enabled=False)

    def set_corridor_enabled(self, corridor_id: str, enabled: bool) -> dict[str, Any]:
        """启用或停用一条走廊。"""
        try:
            result = green_wave_functions.set_green_wave_corridor_enabled(
                {"corridor_id": corridor_id, "enabled": enabled}
            )
            return adapt_enabled_result(result)
        except Exception as error:
            return self._error(f"更新绿波走廊状态失败: {error}")

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"status": "error", "saved": False, "reason": message}
