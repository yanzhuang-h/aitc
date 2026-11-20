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
        self._batch_id: str | None = None

    def replace(
        self, results: Sequence[DecisionResult | Mapping[str, Any]], *, batch_id: str | None = None,
    ) -> None:
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
            self._batch_id = batch_id

    def snapshot(self) -> list[dict[str, Any]]:
        return self.snapshot_with_batch()[0]

    def snapshot_with_batch(self) -> tuple[list[dict[str, Any]], str | None]:
        """在同一把锁下取出报文和对应的决策批次号。"""
        with self._lock:
            return copy.deepcopy(self._results), self._batch_id
