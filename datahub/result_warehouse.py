"""运行结果仓库。"""

from __future__ import annotations

import copy
from threading import Lock
from typing import Any, Mapping, Sequence

from app.core.models import DecisionResult


class ResultWarehouse:
    """先沿用内存列表作为结果仓库，后续可替换为 Redis、文件或数据库。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._results: list[dict[str, Any]] = []

    def replace(self, results: Sequence[DecisionResult | Mapping[str, Any]]) -> None:
        """替换最新结果，同时接受领域模型与既有协议字典。"""
        normalized = []
        for result in results:
            if isinstance(result, DecisionResult):
                normalized.append(result.to_payload())
                continue
            # 仓库保留对历史测试、回放和旧调用方的通用字典兼容。
            try:
                normalized.append(DecisionResult.from_payload(result).to_payload())
            except ValueError:
                normalized.append(copy.deepcopy(dict(result)))
        with self._lock:
            self._results = normalized

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._results)
