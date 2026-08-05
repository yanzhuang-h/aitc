"""运行结果仓库。"""

from __future__ import annotations

from threading import Lock
from typing import Any


class ResultWarehouse:
    """先沿用内存列表作为结果仓库，后续可替换为 Redis、文件或数据库。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._results: list[dict[str, Any]] = []

    def replace(self, results: list[dict[str, Any]]) -> None:
        with self._lock:
            self._results = list(results)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._results)

