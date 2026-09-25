"""轻量日志混入：统一 _debug/_info/_warning/_error 样板。

持有 self.logger 的类继承本混入即可；logger 为 None 时静默（测试/兼容场景）。
"""

from __future__ import annotations

from typing import Any


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
