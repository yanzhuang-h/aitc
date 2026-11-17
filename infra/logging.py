"""轻量日志混入：统一 _debug/_info/_warning/_error 样板。

持有 self.logger 的类继承本混入即可；logger 为 None 时静默（测试/兼容场景）。
"""

from __future__ import annotations

from typing import Any
from contextvars import ContextVar
import hashlib
import json


class LoggingMixin:
    """为持有 logger 属性的类提供分级日志快捷方法。"""

    logger: Any | None

    def _debug(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.debug(message, *args)

    def _info(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.info(message, *args)

    def _warning(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.warning(message, *args)

    def _error(self, message: str, *args: Any, **kwargs: Any) -> None:
        if self.logger is not None:
            self.logger.error(message, *args, **kwargs)


# 每轮主线程与其工作线程共用批次号，不进入协议报文。
decision_batch_id = ContextVar("aitc_decision_batch_id", default=None)


def plan_fingerprint(tl_logic):
    """计算实际格式化方案的稳定指纹，用于关联决策记录与本地发送日志。"""
    return hashlib.sha256(json.dumps(
        tl_logic, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
