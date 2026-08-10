"""输出控制抽象：把校验后的方案下发信控平台。"""

from __future__ import annotations

from typing import Any, Protocol


class OutputDispatcher(Protocol):
    """输出控制抽象。

    把安全校验通过的控制方案打包为对外协议并发送到信控平台，
    同时记录发送日志与下发状态。
    """

    def dispatch(self, plans: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """下发一组控制方案，返回发送记录列表。"""
