"""输出控制：把安全校验通过的控制方案下发信控平台。

后续将包装现有 runtime.result_formatter（协议打包）与结果发送器，
统一为控制层的输出出口。
"""

from __future__ import annotations

import logging
from typing import Any


class ControlOutputDispatcher:
    """控制方案输出下发。"""

    def __init__(self, formatter: Any | None = None, logger: logging.Logger | None = None) -> None:
        self.formatter = formatter
        self.logger = logger or logging.getLogger("aitc.control.output")

    def dispatch(self, plans: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """下发一组控制方案，返回发送记录。

        骨架实现：先原样返回方案清单；接入协议格式化与发送器后
        返回真实发送记录。
        """
        return [{"cross_id": cross_id, "plan": plan} for cross_id, plan in plans.items()]
